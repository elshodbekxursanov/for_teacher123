from rest_framework.permissions import BasePermission


class HasActiveAccess(BasePermission):
    """Kirgan + faol obuna + (kerak bo'lsa) parol almashtirilgan."""
    message = "Obuna faol emas yoki avval parolni almashtirish kerak"

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.has_active_access and not u.must_change_password)


class IsLoggedIn(BasePermission):
    """Faqat kirganlik (obunasi tugagan yoki parol almashtirishi kerak bo'lganlar ham) — to'lov, profil uchun."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_active)


def _role(*roles):
    class _P(HasActiveAccess):
        def has_permission(self, request, view):
            return super().has_permission(request, view) and (request.user.is_admin_role or request.user.role in roles)
    return _P

IsTeacher = _role("teacher")      # admin ham o'tadi
IsAdminRole = _role()             # faqat admin
