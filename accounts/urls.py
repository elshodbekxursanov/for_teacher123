from django.urls import include, path
from rest_framework.permissions import AllowAny
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

router = DefaultRouter()
router.register("admin/users", views.AdminUserViewSet, basename="admin-users")


class Refresh(TokenRefreshView):
    permission_classes = [AllowAny]


urlpatterns = [
    path("auth/login/", views.LoginView.as_view()),
    path("auth/refresh/", Refresh.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),
    path("auth/register/", views.RegisterView.as_view()),
    path("auth/change-password/", views.ChangePasswordView.as_view()),
    path("auth/me/", views.MeView.as_view()),
    path("admin/settings/", views.SiteConfigView.as_view()),
    path("admin/audit/", views.AuditView.as_view()),
    path("", include(router.urls)),
]
