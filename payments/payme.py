"""Payme Merchant API (JSON-RPC 2.0). Summalar tiyinda. Har doim HTTP 200 qaytariladi."""
import base64, hmac, time
from django.conf import settings
from django.db import transaction
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Payment

TIMEOUT_MS = 12 * 3600 * 1000


class PaymeError(Exception):
    def __init__(self, code, uz, ru="", en="", data=None):
        self.code, self.msg, self.data = code, {"uz": uz, "ru": ru or uz, "en": en or uz}, data


E_AUTH = (-32504, "Avtorizatsiya xatosi")
E_AMOUNT = (-31001, "Noto'g'ri summa")
E_NO_ORDER = (-31050, "Buyurtma topilmadi")
E_ORDER_STATE = (-31051, "Buyurtma holati noto'g'ri")
E_BUSY = (-31052, "Buyurtma band")
E_NO_TX = (-31003, "Tranzaksiya topilmadi")
E_CANT_PERFORM = (-31008, "Amalni bajarib bo'lmaydi")
E_CANT_CANCEL = (-31007, "Bekor qilib bo'lmaydi")


def now_ms():
    return int(time.time() * 1000)


def _order(params):
    try:
        pay = Payment.objects.select_for_update().select_related("user").get(pk=int(params["account"]["order_id"]))
    except (KeyError, ValueError, TypeError, Payment.DoesNotExist):
        raise PaymeError(*E_NO_ORDER, data="order_id")
    if int(params.get("amount", -1)) != pay.amount * 100:
        raise PaymeError(*E_AMOUNT)
    return pay


def _tx(params):
    pay = Payment.objects.select_for_update().select_related("user").filter(provider="payme", provider_tx_id=params.get("id")).first()
    if not pay:
        raise PaymeError(*E_NO_TX)
    return pay


def _cancel(pay, reason, state=-1):
    pay.payme_state, pay.payme_reason, pay.payme_cancel_time = state, reason, now_ms()
    pay.status = Payment.Status.CANCELLED
    pay.save()


def check_perform(p):
    pay = _order(p)
    if pay.status != Payment.Status.PENDING:
        raise PaymeError(*E_ORDER_STATE)
    return {"allow": True}


def create_tx(p):
    existing = Payment.objects.select_for_update().filter(provider="payme", provider_tx_id=p.get("id")).first()
    if existing:
        if existing.payme_state != 1:
            raise PaymeError(*E_CANT_PERFORM)
        if now_ms() - existing.payme_create_time > TIMEOUT_MS:
            _cancel(existing, 4)
            raise PaymeError(*E_CANT_PERFORM)
        return {"create_time": existing.payme_create_time, "transaction": str(existing.pk), "state": 1}
    pay = _order(p)
    if pay.status != Payment.Status.PENDING:
        raise PaymeError(*E_ORDER_STATE)
    if pay.provider == "payme" and pay.payme_state == 1:
        raise PaymeError(*E_BUSY)                               # boshqa tranzaksiya kutmoqda
    pay.provider, pay.provider_tx_id, pay.payme_state, pay.payme_create_time = "payme", p["id"], 1, now_ms()
    pay.save()
    return {"create_time": pay.payme_create_time, "transaction": str(pay.pk), "state": 1}


def perform_tx(p):
    pay = _tx(p)
    if pay.payme_state == 1:
        if now_ms() - pay.payme_create_time > TIMEOUT_MS:
            _cancel(pay, 4)
            raise PaymeError(*E_CANT_PERFORM)
        services.activate(pay, "payme", p["id"])
        pay.payme_state, pay.payme_perform_time = 2, now_ms()
        pay.save()
    elif pay.payme_state != 2:
        raise PaymeError(*E_CANT_PERFORM)
    return {"perform_time": pay.payme_perform_time, "transaction": str(pay.pk), "state": pay.payme_state}


def cancel_tx(p):
    pay = _tx(p)
    if pay.payme_state == 1:
        _cancel(pay, p.get("reason"), -1)
    elif pay.payme_state == 2:
        services.revoke(pay)
        _cancel(pay, p.get("reason"), -2)
    return {"cancel_time": pay.payme_cancel_time, "transaction": str(pay.pk), "state": pay.payme_state}


def check_tx(p):
    pay = _tx(p)
    return {"create_time": pay.payme_create_time, "perform_time": pay.payme_perform_time,
            "cancel_time": pay.payme_cancel_time, "transaction": str(pay.pk),
            "state": pay.payme_state, "reason": pay.payme_reason}


def statement(p):
    qs = Payment.objects.filter(provider="payme", payme_create_time__gte=p["from"], payme_create_time__lte=p["to"])
    return {"transactions": [{
        "id": x.provider_tx_id, "time": x.payme_create_time, "amount": x.amount * 100,
        "account": {"order_id": str(x.pk)}, "create_time": x.payme_create_time,
        "perform_time": x.payme_perform_time, "cancel_time": x.payme_cancel_time,
        "transaction": str(x.pk), "state": x.payme_state, "reason": x.payme_reason} for x in qs]}


METHODS = {"CheckPerformTransaction": check_perform, "CreateTransaction": create_tx,
           "PerformTransaction": perform_tx, "CancelTransaction": cancel_tx,
           "CheckTransaction": check_tx, "GetStatement": statement}


def _authorized(request):
    h = request.headers.get("Authorization", "")
    if not h.startswith("Basic "):
        return False
    try:
        got = base64.b64decode(h[6:]).decode()
    except Exception:
        return False
    return hmac.compare_digest(got, f"Paycom:{settings.PAYME_KEY}")


class PaymeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        rid = request.data.get("id") if isinstance(request.data, dict) else None

        def err(e):
            return Response({"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.msg, "data": e.data}})
        if not _authorized(request):
            return err(PaymeError(*E_AUTH))
        fn = METHODS.get(request.data.get("method"))
        if not fn:
            return err(PaymeError(-32601, "Metod topilmadi"))
        try:
            with transaction.atomic():
                result = fn(request.data.get("params") or {})
        except PaymeError as e:
            return err(e)
        return Response({"jsonrpc": "2.0", "id": rid, "result": result})
