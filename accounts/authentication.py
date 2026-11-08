from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import SiteConfig


class SessionJWTAuthentication(JWTAuthentication):
    """Sozlama yoqilgan bo'lsa, faqat eng so'nggi kirishdagi token ishlaydi (bitta faol sessiya)."""
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if user.active_sid and SiteConfig.get().single_session and validated_token.get("sid") != user.active_sid:
            raise AuthenticationFailed("Hisobingizga boshqa qurilmadan kirilgan", code="session_replaced")
        return user
