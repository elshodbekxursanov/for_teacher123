from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from materials.models import Material
from quizzes.models import Test
from .services import notify_students


@receiver(post_save, sender=Test)
def test_created(sender, instance, created, **kw):
    if created and instance.is_published:
        notify_students("Yangi test", f"{instance.title} — {instance.question_count} ta savol", "/tests")


@receiver(pre_save, sender=Material)
def material_remember(sender, instance, **kw):
    old = Material.objects.filter(pk=instance.pk).values_list("status", flat=True).first() if instance.pk else None
    instance._was_published = old == Material.Status.PUBLISHED


@receiver(post_save, sender=Material)
def material_published(sender, instance, **kw):
    if instance.status == Material.Status.PUBLISHED and not getattr(instance, "_was_published", False) and instance.access == Material.Access.ALL:
        notify_students("Yangi material", instance.title, "/materials")
