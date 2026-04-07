from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from main.models import Notification


@receiver(pre_save, sender=User)
def detect_sensitive_changes(sender, instance, **kwargs):

    if not instance.pk:
        return

    old_user = User.objects.get(pk=instance.pk)

    if old_user.email != instance.email:
        Notification.objects.create(
            user=instance,
            message="Your email was modified by an administrator."
        )

    if old_user.username != instance.username:
        Notification.objects.create(
            user=instance,
            message="Your username was modified by an administrator."
        )