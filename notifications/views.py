from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification


class MyNotifications(APIView):
    """Oxirgi 20 ta xabar va o'qilmaganlar soni."""

    def get(self, request):
        qs = Notification.objects.filter(user=request.user)
        return Response({"unread": qs.filter(is_read=False).count(),
                         "results": [{"id": n.id, "title": n.title, "text": n.text, "link": n.link,
                                      "is_read": n.is_read, "created_at": n.created_at} for n in qs[:20]]})


class MarkRead(APIView):
    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({"unread": 0})
