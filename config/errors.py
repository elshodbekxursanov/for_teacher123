from rest_framework.views import exception_handler

def api_exception_handler(exc, context):
    resp = exception_handler(exc, context)
    if resp is not None:
        resp.data = {"error": {"status": resp.status_code, "detail": resp.data}}
    return resp
