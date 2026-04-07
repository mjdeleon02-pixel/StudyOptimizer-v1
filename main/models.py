from django.db import models
from django.contrib.auth.models import User
import pyotp
import hashlib
from django.db.models.signals import pre_save
from django.dispatch import receiver
from cryptography.fernet import Fernet
import base64
from django.conf import settings


# ─── Encryption ───────────────────────────────────────────────────────────────

_CIPHER_SUITE = Fernet(base64.urlsafe_b64encode(settings.SECRET_KEY.encode()[:32].ljust(32, b'0')))


# ─── User Profile ─────────────────────────────────────────────────────────────

class UserProfile(models.Model):
    """
    Merged from UserProfile (TOTP/security) + Profile (bio/academic info).
    """
    user        = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')

    # Security (from original UserProfile)
    totp_secret  = models.CharField(max_length=32, blank=True, null=True)
    totp_enabled = models.BooleanField(default=False)

    # Academic / social (from new Profile)
    bio      = models.TextField(max_length=500, blank=True, default="No bio yet... ✍️")
    major    = models.CharField(max_length=100, blank=True, default="General Studies 🎓")
    location = models.CharField(max_length=100, blank=True, default="Focus Room 📚")
    streak   = models.IntegerField(default=0)

    def generate_totp_secret(self):
        if not self.totp_secret:
            self.totp_secret = pyotp.random_base32()
            self.save()
        return self.totp_secret

    def __str__(self):
        return f"{self.user.username}'s Profile"


# ─── Task ─────────────────────────────────────────────────────────────────────

class Task(models.Model):
    PRIORITY_CHOICES = [
        ('Low',    'Low'),
        ('Medium', 'Medium'),
        ('High',   'High'),
    ]
    CATEGORY_CHOICES = [
        ('General',  'General'),
        ('Project',  'Project'),
        ('Research', 'Research'),
        ('Revision', 'Revision'),
    ]
    PERIOD_CHOICES = [
        ('General',  'General'),
        ('Prelims',  'Prelims'),
        ('Midterms', 'Midterms'),
        ('Finals',   'Finals'),
    ]

    user      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tasks')
    title     = models.CharField(max_length=255)
    subject   = models.CharField(max_length=100, default='General')
    category  = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='General')
    period    = models.CharField(max_length=20, choices=PERIOD_CHOICES, default='General')
    priority  = models.CharField(max_length=10, choices=PRIORITY_CHOICES)
    due_date  = models.DateField()
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['completed', 'due_date']


# ─── Shared Material ──────────────────────────────────────────────────────────

class SharedMaterial(models.Model):
    CATEGORY_CHOICES = [
        ('General',         'General'),
        ('Shared Resource', 'Shared Resource'),
        ('Discussion',      'Discussion'),
        ('Revision',        'Review'),
    ]
    PERIOD_CHOICES = [
        ('General',  'General'),
        ('Prelims',  'Prelims'),
        ('Midterms', 'Midterms'),
        ('Finals',   'Finals'),
    ]

    author       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shared_materials')
    title        = models.CharField(max_length=255)
    subject      = models.CharField(max_length=100)
    category     = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='General')
    period       = models.CharField(max_length=20, choices=PERIOD_CHOICES, default='General')
    content      = models.TextField()
    file         = models.FileField(upload_to='shared_files/', null=True, blank=True)
    likes        = models.ManyToManyField(User, related_name='liked_materials', blank=True)
    views        = models.IntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)
    is_anonymous = models.BooleanField(default=False)
    is_hidden    = models.BooleanField(default=False)
    emoji        = models.CharField(max_length=10, default='📄')

    def __str__(self):
        return self.title

    @property
    def likes_count(self):
        return self.likes.count()


# ─── Comment ──────────────────────────────────────────────────────────────────

class Comment(models.Model):
    material   = models.ForeignKey(SharedMaterial, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User, on_delete=models.CASCADE)
    text       = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment by {self.author.username} on {self.material.title}"


# ─── Summarized Document ──────────────────────────────────────────────────────

class SummarizedDocument(models.Model):
    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name='summaries')
    file_name    = models.CharField(max_length=255)
    category     = models.CharField(max_length=20, default='General')
    period       = models.CharField(max_length=20, default='General')
    subject      = models.CharField(max_length=100, default='General')
    summary_text = models.TextField()
    content_hash = models.CharField(max_length=64, blank=True, help_text="SHA-256 integrity hash")
    emoji        = models.CharField(max_length=10, default='📄')
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.file_name


# ─── Schedule Item ────────────────────────────────────────────────────────────

class ScheduleItem(models.Model):
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='schedule_items')
    day      = models.CharField(max_length=20)
    date     = models.DateField(null=True, blank=True)
    time     = models.CharField(max_length=50)
    activity = models.CharField(max_length=255)
    color    = models.CharField(max_length=20, default='blue')

    def __str__(self):
        return f"{self.day}: {self.activity}"


# ─── Security Models ──────────────────────────────────────────────────────────

class PasswordHistory(models.Model):
    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_history')
    password_hash = models.CharField(max_length=128)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    previous_hash = models.CharField(max_length=64, blank=True)
    current_hash = models.CharField(max_length=64, blank=True)

    def save(self, *args, **kwargs):
        if not self.pk:
            last_entry = AuditLog.objects.order_by("-timestamp").first()
            self.previous_hash = last_entry.current_hash if last_entry else "GENESIS"
            payload = f"{self.user}{self.action}{self.details}{self.timestamp}{self.previous_hash}"
            self.current_hash = hashlib.sha256(payload.encode()).hexdigest()
        super().save(*args, **kwargs)

class KnownIP(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='known_ips')
    ip_address = models.GenericIPAddressField()
    last_used  = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.ip_address}"


class Notification(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message    = models.TextField()
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for {self.user.username}"


# ─── Signals ──────────────────────────────────────────────────────────────────

@receiver(pre_save, sender=SummarizedDocument)
def verify_document_integrity(sender, instance, **kwargs):
    """STRIDE — Tampering Protection: keeps content_hash in sync with summary_text."""
    if not instance.summary_text:
        return
    calc_hash = hashlib.sha256(instance.summary_text.encode('utf-8')).hexdigest()
    if not instance.content_hash or instance.content_hash != calc_hash:
        instance.content_hash = calc_hash