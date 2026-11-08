from django.conf import settings
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole, IsLoggedIn
from . import services
from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Payment
        fields = ["id", "user", "username", "plan", "amount", "status", "provider", "created_at", "paid_at"]


class PlansView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response([{"id": k, "name": v["name"], "price": v["price"]} for k, v in settings.PLANS.items()])


class CreatePaymentView(APIView):
    """Tarif tanlash -> kutilayotgan to'lov. Summa FAQAT serverdagi tarifdan olinadi."""
    permission_classes = [IsLoggedIn]
    throttle_scope = "payment"

    def post(self, request):
        plan = request.data.get("plan")
        if plan not in settings.PLANS:
            return Response({"detail": "Noto'g'ri tarif"}, status=400)
        pay = Payment.objects.create(user=request.user, plan=plan, amount=settings.PLANS[plan]["price"])
        return Response({**PaymentSerializer(pay).data, "checkout": services.checkout_urls(pay)}, status=201)


class MyPaymentsView(ListAPIView):
    permission_classes = [IsLoggedIn]
    serializer_class = PaymentSerializer
    pagination_class = None

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user)


class AdminPaymentsView(ListAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = PaymentSerializer
    queryset = Payment.objects.select_related("user")
