from django.core.mail import send_mail
from django.conf import settings
from .models import AuditLog

# main/utils.py
from django.core.mail import send_mail
from django.conf import settings
from .models import AuditLog
from django.contrib.auth.models import User

def log_action(user, action, details="", request=None):
    """Creates a new AuditLog entry with chained hash and IP tracking."""
    ip_address = "Unknown"
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip_address = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
    
    full_details = f"IP: {ip_address} | {details}"
    
    # AuditLog.save() handles the hashing automatically
    AuditLog.objects.create(user=user, action=action, details=full_details)
    
def send_security_alert(user: User, subject: str, message: str):
    """
    Sends a security alert email to the user and logs it in AuditLog.
    """
    full_message = f"Hello {user.username},\n\n{message}\n\nIf this wasn't you, please change your password immediately and contact support."
    
    send_mail(
        f"Security Alert: {subject}",
        full_message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
    )


    # Log the security alert to AuditLog using log_action
    log_action(user, "Security Alert Sent", f"Subject: {subject}")