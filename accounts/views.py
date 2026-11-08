import secrets
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from payments.models import Payment
from payments.services import checkout_urls
from .models import AuditLog, SiteConfig, User, audit
from .permissions import IsAdminRole, IsLoggedIn
from .serializers import (AdminUserSerializer, ChangePasswordSerializer, LoginSerializer, MeSerializer,
                          RegisterSerializer, SiteConfigSerializer)

MAX_FAILS, LOCK_SECONDS = 5, 900


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_scope = "login"

    def post(self, request, *a, **kw):
        key = "loginfail:" + str(request.data.get("username", "")).lower()[:150]
        if cache.get(key, 0) >= MAX_FAILS:           # ketma-ket xato paroldan keyin vaqtincha bloklash
            return Response({"error": {"status": 429, "detail": "Juda ko'p xato urinish. 15 daqiqadan keyin qayta urinib ko'ring"}}, status=429)
        try:
            resp = super().post(request, *a, **kw)
        except (AuthenticationFailed, InvalidToken):
            cache.set(key, cache.get(key, 0) + 1, LOCK_SECONDS)
            raise
        cache.delete(key)
        return resp


class LogoutView(APIView):
    permission_classes = [IsLoggedIn]

    def post(self, request):
        try:
            RefreshToken(request.data.get("refresh")).blacklist()
        except Exception:
            pass
        return Response(status=204)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "register"

    @transaction.atomic
    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        user = User(username=d["username"], first_name=d["first_name"], role=User.Role.STUDENT, access_type=User.Access.PAID)
        user.set_password(d["password"])
        user.save()
        pay = Payment.objects.create(user=user, plan=d["plan"], amount=settings.PLANS[d["plan"]]["price"])
        refresh = RefreshToken.for_user(user)
        return Response({"user": MeSerializer(user).data, "payment_id": pay.id, "amount": pay.amount,
                         "checkout": checkout_urls(pay), "access": str(refresh.access_token), "refresh": str(refresh)}, status=201)


class MeView(APIView):
    permission_classes = [IsLoggedIn]

    def get(self, request):
        return Response(MeSerializer(request.user).data)

    def patch(self, request):
        s = MeSerializer(request.user, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request):
        """Foydalanuvchi o'z hisobini o'chiradi (parol bilan tasdiqlanadi)."""
        if request.user.is_admin_role:
            return Response({"detail": "Administrator hisobini bu yerdan o'chirib bo'lmaydi"}, status=400)
        if not request.user.check_password(request.data.get("password", "")):
            return Response({"detail": "Parol noto'g'ri"}, status=400)
        audit(request.user, "account_deleted", request.user.username)
        request.user.delete()
        return Response(status=204)


class ChangePasswordView(APIView):
    permission_classes = [IsLoggedIn]

    def post(self, request):
        s = ChangePasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if not request.user.check_password(s.validated_data["old_password"]):
            return Response({"detail": "Eski parol noto'g'ri"}, status=400)
        request.user.set_password(s.validated_data["new_password"])
        request.user.must_change_password = False
        request.user.save()
        return Response({"ok": True})


class AdminUserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    serializer_class = AdminUserSerializer

    def get_queryset(self):
        qs = User.objects.all().order_by("-date_joined")
        q = self.request.query_params.get("q")
        return qs.filter(username__icontains=q) | qs.filter(first_name__icontains=q) if q else qs

    def perform_create(self, s):
        u = s.save(); audit(self.request.user, "user_created", u.username)

    def perform_update(self, s):
        u = s.save(); audit(self.request.user, "user_updated", u.username)

    def perform_destroy(self, inst):
        audit(self.request.user, "user_deleted", inst.username); inst.delete()

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        pwd = request.data.get("password") or secrets.token_urlsafe(8)
        user.set_password(pwd)
        user.must_change_password = True
        user.save()
        audit(request.user, "password_reset", user.username)
        return Response({"password": pwd})          # faqat shu javobda ko'rinadi


class SiteConfigView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        return Response(SiteConfigSerializer(SiteConfig.get()).data)

    def patch(self, request):
        s = SiteConfigSerializer(SiteConfig.get(), data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save(); audit(request.user, "settings_changed", str(request.data)[:150])
        return Response(s.data)


class AuditView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        rows = AuditLog.objects.select_related("user")[:200]
        return Response([{"id": r.id, "user": r.user.username if r.user else "", "action": r.action,
                          "object": r.object, "created_at": r.created_at} for r in rows])
