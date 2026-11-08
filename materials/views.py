import mimetypes
import os
from django.core import signing
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User, audit
from accounts.permissions import HasActiveAccess, IsAdminRole
from config.background import run_bg
from django.conf import settings
from . import extract, index
from .models import Material, MaterialAccess, MaterialFile, ProblemSource
from .serializers import MaterialAdminSerializer, SourceSerializer

LINK_TTL = 120      # soniya


def accessible_materials(user):
    """Foydalanuvchi ko'ra oladigan materiallar (AI ham faqat shulardan qidiradi)."""
    qs = Material.objects.filter(is_archived=False)
    if user.is_admin_role:
        return qs
    return qs.filter(status="published").filter(Q(access="all") | Q(access="selected", materialaccess__user=user)).distinct()


def can_download(user, m):
    return user.is_admin_role or m.allow_download


def save_files(material, files, user):
    """Yuklangan fayllarni tekshirib saqlaydi (turi, hajmi, antivirus, checksum) va indekslashni fonda boshlaydi."""
    made = []
    for f in files:
        ext = os.path.splitext(f.name)[1].lower().lstrip(".")
        if ext not in extract.ALLOWED:
            raise ValidationError(f"Fayl turi ruxsat etilmagan: .{ext}")
        if f.size > settings.MAX_MATERIAL_BYTES:
            raise ValidationError(f"{f.name}: fayl {settings.MAX_MATERIAL_BYTES // 1048576} MB dan oshmasligi kerak")
        ok, why = index.scan_upload(f)
        if not ok:
            raise ValidationError(f"{f.name}: antivirus tekshiruvidan o'tmadi ({why})")
        mf = MaterialFile.objects.create(material=material, file=f, original_name=os.path.basename(f.name)[:255], ext=ext,
                                         size=f.size, checksum=index.sha256(f))
        audit(user, "material_file_uploaded", f"{material.id}:{mf.original_name}")
        made.append(mf)
    for mf in made:
        run_bg("materials.index:index_file", mf.id, False)
    return made


class AdminMaterialViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    serializer_class = MaterialAdminSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Material.objects.select_related("subject").prefetch_related("files", "materialaccess_set")
        p = self.request.query_params
        if p.get("month"):
            qs = qs.filter(month=p["month"])
        if p.get("subject"):
            qs = qs.filter(subject_id=p["subject"])
        return qs

    def _apply_users(self, m):
        ids = self.request.data.getlist("access_users") if hasattr(self.request.data, "getlist") else self.request.data.get("access_users")
        if ids is not None:
            m.allowed_users.set(User.objects.filter(pk__in=[int(i) for i in ids if str(i).isdigit()]))
        logins = self.request.data.get("access_logins")           # "ali, vali" ko'rinishida ham beriladi
        if logins is not None:
            names = [x.strip() for x in str(logins).replace("\n", ",").split(",") if x.strip()]
            m.allowed_users.set(User.objects.filter(username__in=names))

    def perform_create(self, s):
        m = s.save(uploaded_by=self.request.user)
        self._apply_users(m)
        files = self.request.FILES.getlist("files")
        try:
            save_files(m, files, self.request.user)
        except ValidationError:
            m.delete(); raise
        audit(self.request.user, "material_created", m.title)

    def perform_update(self, s):
        m = s.save(); self._apply_users(m)
        files = self.request.FILES.getlist("files")
        if files:
            save_files(m, files, self.request.user)
        audit(self.request.user, "material_updated", m.title)

    def perform_destroy(self, m):
        audit(self.request.user, "material_deleted", m.title); m.delete()

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        m = self.get_object(); m.is_archived = not m.is_archived; m.save()
        audit(request.user, "material_archived" if m.is_archived else "material_unarchived", m.title)
        return Response(MaterialAdminSerializer(m).data)

    @action(detail=True, methods=["delete"], url_path=r"files/(?P<fid>\d+)")
    def delete_file(self, request, pk=None, fid=None):
        mf = self.get_object().files.filter(pk=fid).first()
        if not mf:
            raise Http404
        audit(request.user, "material_file_deleted", mf.original_name); mf.file.delete(save=False); mf.delete()
        return Response(status=204)

    @action(detail=True, methods=["post"], url_path=r"files/(?P<fid>\d+)/replace")
    def replace_file(self, request, pk=None, fid=None):
        m = self.get_object()
        old = m.files.filter(pk=fid).first()
        new = request.FILES.get("file")
        if not old or not new:
            raise ValidationError("Fayl yoki material topilmadi")
        save_files(m, [new], request.user)
        old.file.delete(save=False); old.delete()
        return Response(MaterialAdminSerializer(m).data)

    @action(detail=True, methods=["post"])
    def reindex(self, request, pk=None):
        """Matn ajratish va indekslashni qayta ishga tushirish. use_ai=true: skaner PDF larni Claude orqali o'qiydi."""
        m = self.get_object()
        use_ai = bool(request.data.get("use_ai"))
        if use_ai and not settings.ANTHROPIC_API_KEY:
            raise ValidationError("ANTHROPIC_API_KEY sozlanmagan")
        for mf in m.files.all():
            mf.extract_status = "pending"; mf.save(update_fields=["extract_status"])
            run_bg("materials.index:index_file", mf.id, use_ai)
        return Response({"started": m.files.count()}, status=202)

    @action(detail=True, methods=["get", "patch"])
    def index(self, request, pk=None):
        """Indeks tekshiruvi: topilgan misollarni ko'rish va tuzatish."""
        m = self.get_object()
        qs = ProblemSource.objects.filter(file__material=m).select_related("file")
        if request.method == "PATCH":
            for ch in request.data if isinstance(request.data, list) else request.data.get("items", []):
                src = qs.filter(pk=ch.get("id")).first()
                if not src:
                    continue
                if ch.get("delete"):
                    src.delete(); continue
                for k in ("number", "topic_label", "text", "solution_text", "verified"):
                    if k in ch:
                        setattr(src, k, ch[k])
                src.save()
            audit(request.user, "index_corrected", m.title)
            qs = ProblemSource.objects.filter(file__material=m).select_related("file")
        return Response(SourceSerializer(qs[:1000], many=True).data)


class MaterialListView(APIView):
    """Foydalanuvchi uchun: oy va fan bo'yicha (ruxsat bo'yicha)."""
    permission_classes = [HasActiveAccess]

    def get(self, request):
        qs = accessible_materials(request.user).select_related("subject", "topic").prefetch_related("files")
        p = request.query_params
        if p.get("month"):
            qs = qs.filter(month=p["month"])
        if p.get("subject"):
            qs = qs.filter(subject_id=p["subject"])
        qs = qs.filter(subject__is_active=True)
        return Response([{
            "id": m.id, "title": m.title, "subject": m.subject_id, "subject_name": m.subject.name,
            "topic_name": m.topic.name if m.topic else "", "month": m.month, "description": m.description,
            "files": [{"id": f.id, "name": f.original_name, "ext": f.ext, "size": f.size,
                       "can_download": can_download(request.user, m)} for f in m.files.all()]} for m in qs])


class FileLinkView(APIView):
    """Qisqa muddatli imzolangan havola beradi (faqat ruxsati borga)."""
    permission_classes = [HasActiveAccess]

    def get(self, request, pk):
        mf = MaterialFile.objects.select_related("material").filter(pk=pk).first()
        if not mf or not accessible_materials(request.user).filter(pk=mf.material_id).exists():
            raise PermissionDenied("Bu faylga ruxsatingiz yo'q")
        dl = request.query_params.get("download") == "1"
        if dl and not can_download(request.user, mf.material):
            raise PermissionDenied("Bu materialni yuklab olish mumkin emas")
        token = signing.dumps({"u": request.user.id, "f": mf.id, "d": dl}, salt="matfile")
        return Response({"url": f"/api/materials/files/{mf.id}/view/?t={token}", "expires_in": LINK_TTL})


class FileView(APIView):
    """Imzolangan havola bo'yicha faylni beradi. Token foydalanuvchiga bog'langan va tez eskiradi."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk):
        try:
            data = signing.loads(request.query_params.get("t", ""), salt="matfile", max_age=LINK_TTL)
        except signing.BadSignature:
            return HttpResponse("Havola yaroqsiz yoki muddati tugagan", status=403)
        user = User.objects.filter(pk=data["u"], is_active=True).first()
        mf = MaterialFile.objects.select_related("material").filter(pk=pk).first()
        if data["f"] != pk or not user or not user.has_active_access or not mf or \
                not accessible_materials(user).filter(pk=mf.material_id).exists():
            return HttpResponse("Ruxsat yo'q", status=403)
        if not os.path.exists(mf.file.path):
            raise Http404
        resp = FileResponse(open(mf.file.path, "rb"), as_attachment=bool(data["d"]) and can_download(user, mf.material),
                            filename=mf.original_name, content_type=mimetypes.guess_type(mf.original_name)[0] or "application/octet-stream")
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "private, no-store"
        return resp
