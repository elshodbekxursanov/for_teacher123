from .models import Notification


def notify(user, title, text="", link=""):
    return Notification.objects.create(user=user, title=title[:160], text=text[:300], link=link[:120])


def notify_students(title, text="", link=""):
    """Barcha faol o'quvchilarga bir martada (bulk) xabar yuboradi."""
    from accounts.models import User
    ids = User.objects.filter(role="student", is_active=True).values_list("id", flat=True)
    Notification.objects.bulk_create(
        [Notification(user_id=i, title=title[:160], text=text[:300], link=link[:120]) for i in ids], batch_size=500)
