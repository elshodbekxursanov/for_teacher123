"""Click SHOP-API: Prepare (action=0) va Complete (action=1). Summa so'mda, imzo — MD5."""
import hashlib, hmac
from django.conf import settings
from django.db import transaction
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Payment


def _sign_ok(d, with_prepare):
    parts = [d.get("click_trans_id"), d.get("service_id"), settings.CLICK_SECRET_KEY, d.get("merchant_trans_id")]
    if with_prepare:
        parts.append(d.get("merchant_prepare_id"))
    parts += [d.get("amount"), d.get("action"), d.get("sign_time")]
    mine = hashlib.md5("".join(str(x) for x in parts).encode()).hexdigest()
    return hmac.compare_digest(mine, str(d.get("sign_string", "")).lower())


def _resp(d, error, note, **extra):
    return Response({"click_trans_id": d.get("click_trans_id"), "merchant_trans_id": d.get("merchant_trans_id"),
                     "error": error, "error_note": note, **extra})


class _Base(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    with_prepare = False

    @transaction.atomic
    def post(self, request):
        d = request.data
        if str(d.get("service_id")) != str(settings.CLICK_SERVICE_ID) or not _sign_ok(d, self.with_prepare):
            return _resp(d, -1, "SIGN CHECK FAILED!")
        try:
            pay = Payment.objects.select_for_update().select_related("user").get(pk=int(d.get("merchant_trans_id")))
        except (TypeError, ValueError, Payment.DoesNotExist):
            return _resp(d, -5, "Order not found")
        try:
            if abs(float(d.get("amount", -1)) - pay.amount) > 0.001:
                return _resp(d, -2, "Incorrect parameter amount")
        except (TypeError, ValueError):
            return _resp(d, -8, "Error in request from click")
        return self.handle(d, pay)


class ClickPrepareView(_Base):
    def handle(self, d, pay):
        if str(d.get("action")) != "0":
            return _resp(d, -3, "Action not found")
        if pay.status == Payment.Status.PAID:
            return _resp(d, -4, "Already paid")
        if pay.status == Payment.Status.CANCELLED:
            return _resp(d, -9, "Transaction cancelled")
        pay.provider, pay.click_trans_id = "click", str(d.get("click_trans_id"))
        pay.save()
        return _resp(d, 0, "Success", merchant_prepare_id=pay.pk)


class ClickCompleteView(_Base):
    with_prepare = True

    def handle(self, d, pay):
        if str(d.get("action")) != "1":
            return _resp(d, -3, "Action not found")
        if str(d.get("merchant_prepare_id")) != str(pay.pk) or pay.click_trans_id != str(d.get("click_trans_id")):
            return _resp(d, -6, "Transaction not found")
        if pay.status == Payment.Status.PAID:
            return _resp(d, -4, "Already paid")
        if pay.status == Payment.Status.CANCELLED:
            return _resp(d, -9, "Transaction cancelled")
        if int(d.get("error", 0)) < 0:                       # Click to'lovni bekor qildi
            pay.status = Payment.Status.CANCELLED
            pay.save()
            return _resp(d, -9, "Transaction cancelled")
        services.activate(pay, "click", d.get("click_trans_id"))
        return _resp(d, 0, "Success", merchant_confirm_id=pay.pk)
