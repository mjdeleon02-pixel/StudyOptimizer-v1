"""
views.py — Combined StudyOptimizer views
Merges:
  • Security / MFA / audit features from the original views.py (File 1)
  • Admin panel, analytics, notifications, services layer from the refactored views.py (File 2)
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Avg, Q
from django.db.models.functions import ExtractHour, ExtractWeekDay
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail

import os
try:
    from decouple import config
except ImportError:
    config = os.environ.get

from datetime import date, timedelta, datetime
import json
import re
import io
import random

import bleach
import pyotp
import qrcode
import qrcode.image.svg
import google.generativeai as genai
from django_ratelimit.decorators import ratelimit

from .models import (
    Task, SharedMaterial, Comment, SummarizedDocument,
    ScheduleItem, UserProfile, AuditLog, KnownIP,
    Notification,
)
from .services import (
    extract_text_from_file,
    generate_document_summary,
    generate_batch_synthesis,
    calculate_user_metrics,
    search_summarized_documents,
)
from .utils import send_security_alert


# ── HELPERS ───────────────────────────────────────────────────────────────────

def is_admin(user):
    return user.is_authenticated and (user.is_superuser or user.is_staff)


def _time_ago(dt):
    try:
        diff = int((timezone.now() - dt).total_seconds())
        if diff < 60:    return 'just now'
        if diff < 3600:  m = diff // 60;   return f'{m} minute{"s" if m > 1 else ""} ago'
        if diff < 86400: h = diff // 3600; return f'{h} hour{"s" if h > 1 else ""} ago'
        d = diff // 86400; return f'{d} day{"s" if d > 1 else ""} ago'
    except Exception:
        return 'some time ago'


def _pct_change(old, new):
    if old == 0:
        return '+100%' if new > 0 else '—'
    change = ((new - old) / old) * 100
    return f'{"+" if change >= 0 else ""}{change:.1f}%'


def _quality_score(text):
    l = len(text or '')
    if l > 1500: return 98
    if l > 1000: return 94
    if l > 600:  return 89
    if l > 200:  return 82
    return 70


def _completeness(text):
    l = len(text or '')
    if l > 1500: return 96
    if l > 1000: return 91
    if l > 600:  return 86
    if l > 200:  return 78
    return 65


def _fmt_hour(h):
    h = h % 24
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


# ── PUBLIC / AUTH VIEWS ───────────────────────────────────────────────────────

@csrf_protect
def index(request):
    return render(request, 'main/index.html')


@csrf_protect
def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        # Honeypot (spam-bot protection)
        if request.POST.get('_hp_field'):
            return HttpResponse('Registration successful! (Not really — bot detected)', status=200)

        username  = request.POST.get('username', '').strip()
        email     = request.POST.get('email', '').strip()
        password  = request.POST.get('password', '')
        password2 = request.POST.get('password2', '')

        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        from django.contrib.auth.password_validation import validate_password

        if not re.match(r'^[a-zA-Z0-9_\.\-]{3,150}$', username):
            messages.error(request, 'Invalid username format.')
            return redirect('register')
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, 'Invalid email format.')
            return redirect('register')
        if password != password2:
            messages.error(request, 'Passwords do not match.')
            return redirect('register')
        try:
            validate_password(password, User(username=username, email=email))
        except ValidationError as e:
            for msg in e.messages:
                messages.error(request, msg)
            return redirect('register')
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already taken.')
            return redirect('register')
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email is already registered.')
            return redirect('register')

        User.objects.create_user(username=username, email=email, password=password)
        messages.success(request, 'Account created successfully. Please log in.')
        return redirect('login')

    return render(request, 'main/register.html')


# ── MFA / LOGIN ───────────────────────────────────────────────────────────────

def _start_mfa(request, user):
    """Kick off MFA flow after credentials are verified."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    request.session['mfa_user_id'] = user.id
    if profile.totp_enabled:
        request.session['mfa_method'] = 'totp'
        return redirect('mfa_verify')
    return redirect('setup_totp')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('admin_dashboard' if is_admin(request.user) else 'dashboard')
    if request.method == 'POST':
        email    = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        try:
            user_obj = User.objects.get(email=email)
            user = authenticate(request, username=user_obj.username, password=password)
        except User.DoesNotExist:
            user = None
        if user is not None:
            return _start_mfa(request, user)
        messages.error(request, 'Invalid email or password.')
    return render(request, 'main/login.html')


@csrf_protect
@require_POST
def google_login(request):
    from django.http import Http404
    raise Http404('Google Sign-In is temporarily disabled.')


def setup_totp(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    mfa_user_id = request.session.get('mfa_user_id')
    if not mfa_user_id:
        return redirect('login')

    user = get_object_or_404(User, id=mfa_user_id)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if profile.totp_enabled:
        return redirect('mfa_verify')

    secret = profile.generate_totp_secret()
    totp   = pyotp.TOTP(secret)
    uri    = totp.provisioning_uri(name=user.email, issuer_name='StudyOptimizer')

    factory  = qrcode.image.svg.SvgPathImage
    img      = qrcode.make(uri, image_factory=factory)
    stream   = io.BytesIO()
    img.save(stream)
    svg_data = stream.getvalue().decode()

    if request.method == 'POST':
        if pyotp.TOTP(secret).verify(request.POST.get('otp', '').strip()):
            profile.totp_enabled = True
            profile.save()
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user)
            del request.session['mfa_user_id']
            return redirect('admin_dashboard' if is_admin(user) else 'dashboard')
        messages.error(request, 'Invalid code. Please try scanning again.')

    return render(request, 'main/setup_totp.html', {'qr_code': svg_data, 'secret': secret})


def mfa_verify(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    mfa_user_id = request.session.get('mfa_user_id')
    mfa_method  = request.session.get('mfa_method', 'totp')

    if not mfa_user_id:
        messages.error(request, 'Verification session expired. Please log in again.')
        return redirect('login')

    user = get_object_or_404(User, id=mfa_user_id)
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'send_email':
            otp = f'{random.randint(100000, 999999)}'
            request.session['mfa_otp']    = otp
            request.session['mfa_method'] = 'email'
            try:
                send_mail(
                    'Your Study Optimizer Verification Code',
                    f'Your verification code is: {otp}\n\nPlease enter this code to securely log in.',
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                messages.info(request, 'A verification code has been sent to your email.')
            except Exception as e:
                messages.error(request, f'Failed to send email: {e}')
            return redirect('mfa_verify')

        entered = request.POST.get('otp', '').strip()

        if mfa_method == 'email':
            expected = request.session.get('mfa_otp')
            if expected and entered == str(expected):
                user.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, user)
                for k in ('mfa_user_id', 'mfa_otp', 'mfa_method'):
                    request.session.pop(k, None)
                return redirect('admin_dashboard' if is_admin(user) else 'dashboard')
            messages.error(request, 'Invalid verification code.')
        else:
            if pyotp.TOTP(profile.totp_secret).verify(entered):
                user.backend = 'django.contrib.auth.backends.ModelBackend'

                # New IP detection (STRIDE)
                current_ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
                if not KnownIP.objects.filter(user=user, ip_address=current_ip).exists():
                    send_security_alert(
                        user,
                        'New Login Device Detected',
                        f'Your account was just logged into from a new device or location.\n\n'
                        f'IP Address: {current_ip}\nDate: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                    )
                    KnownIP.objects.create(user=user, ip_address=current_ip)
                else:
                    KnownIP.objects.filter(user=user, ip_address=current_ip).update(last_used=datetime.now())

                login(request, user)
                for k in ('mfa_user_id', 'mfa_method'):
                    request.session.pop(k, None)
                return redirect('admin_dashboard' if is_admin(user) else 'dashboard')
            messages.error(request, 'Invalid authenticator code.')

    return render(request, 'main/mfa_verify.html', {'mfa_method': mfa_method, 'email': user.email})


def logout_view(request):
    logout(request)
    return redirect('home')


# ── ADMIN — DASHBOARD ─────────────────────────────────────────────────────────

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
def admin_dashboard(request):
    now        = timezone.now()
    month_ago  = now - timedelta(days=30)
    prev_month = now - timedelta(days=60)

    total_users   = User.objects.count()
    users_pct     = _pct_change(
        User.objects.filter(date_joined__gte=prev_month, date_joined__lt=month_ago).count(),
        User.objects.filter(date_joined__gte=month_ago).count(),
    )
    total_materials = SharedMaterial.objects.count()
    materials_pct   = _pct_change(
        SharedMaterial.objects.filter(created_at__gte=prev_month, created_at__lt=month_ago).count(),
        SharedMaterial.objects.filter(created_at__gte=month_ago).count(),
    )
    ai_summaries  = SummarizedDocument.objects.count()
    summaries_pct = _pct_change(
        SummarizedDocument.objects.filter(created_at__gte=prev_month, created_at__lt=month_ago).count(),
        SummarizedDocument.objects.filter(created_at__gte=month_ago).count(),
    )
    active_sessions = Session.objects.filter(expire_date__gte=now).count()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    study_labels, study_data = [], []
    for i in range(6, -1, -1):
        day      = today_start - timedelta(days=i)
        next_day = day + timedelta(days=1)
        study_labels.append(day.strftime('%a'))
        study_data.append(
            SharedMaterial.objects.filter(created_at__gte=day, created_at__lt=next_day).count()
        )

    subject_qs     = Task.objects.filter(completed=True).values('subject').annotate(count=Count('id')).order_by('-count')[:6]
    subject_labels = [r['subject'] or 'General' for r in subject_qs]
    subject_data   = [r['count'] for r in subject_qs]

    events = []
    for u in User.objects.filter(date_joined__gte=now - timedelta(hours=24)).order_by('-date_joined')[:5]:
        events.append({'color': 'green', 'message': f'New user <strong>{u.get_full_name() or u.username}</strong> registered.', 'ts': u.date_joined})
    for m in SharedMaterial.objects.select_related('author').filter(created_at__gte=now - timedelta(hours=24)).order_by('-created_at')[:5]:
        events.append({'color': 'blue', 'message': f'<strong>{m.author.get_full_name() or m.author.username}</strong> shared <strong>{m.title}</strong>.', 'ts': m.created_at})
    for s in SummarizedDocument.objects.select_related('user').filter(created_at__gte=now - timedelta(hours=24)).order_by('-created_at')[:5]:
        events.append({'color': 'orange', 'message': f'AI Summary generated for <strong>{s.file_name}</strong>.', 'ts': s.created_at})

    events.sort(key=lambda e: e['ts'], reverse=True)
    recent_activity = [{'color': e['color'], 'message': e['message'], 'time': _time_ago(e['ts'])} for e in events[:10]]

    return render(request, 'main/admin/dashboard.html', {
        'total_users':     total_users,     'users_pct':     users_pct,
        'total_materials': total_materials, 'materials_pct': materials_pct,
        'ai_summaries':    ai_summaries,    'summaries_pct': summaries_pct,
        'active_sessions': active_sessions,
        'study_labels':    json.dumps(study_labels),
        'study_data':      json.dumps(study_data),
        'subject_labels':  json.dumps(subject_labels),
        'subject_data':    json.dumps(subject_data),
        'recent_activity': recent_activity,
    })


# ── ADMIN — USER MANAGEMENT ───────────────────────────────────────────────────

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
def admin_users(request):
    from .models import UserProfile as Profile
    users_qs = (
        User.objects.filter(is_superuser=False)
        .select_related('profile')
        .annotate(task_count=Count('tasks', filter=Q(tasks__completed=True)))
        .order_by('-date_joined')
    )
    user_list = [{
        'id':          u.id,
        'username':    u.username,
        'full_name':   u.get_full_name() or u.username,
        'email':       u.email,
        'is_active':   u.is_active,
        'date_joined': u.date_joined,
        'major':       getattr(getattr(u, 'profile', None), 'major', '—') or '—',
        'streak':      getattr(getattr(u, 'profile', None), 'streak', 0) or 0,
        'task_count':  u.task_count,
        'initials':    u.username[:2].upper(),
    } for u in users_qs]

    return render(request, 'main/admin/user_management.html', {
        'user_list':             user_list,
        'active_users':          sum(1 for u in user_list if u['is_active']),
        'total_tasks_completed': Task.objects.filter(completed=True).count(),
        'avg_streak':            round(Profile.objects.aggregate(a=Avg('streak'))['a'] or 0),
    })


# ── ADMIN — COLLABORATION CONTROL ─────────────────────────────────────────────

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
def admin_collaboration(request):
    materials = (
        SharedMaterial.objects.select_related('author')
        .annotate(like_count=Count('likes', distinct=True), comment_count=Count('comments', distinct=True))
        .order_by('-created_at')
    )
    return render(request, 'main/admin/collaboration_control.html', {
        'material_list': [{
            'id':          m.id,
            'title':       m.title,
            'author_name': m.author.get_full_name() or m.author.username,
            'initials':    m.author.username[:2].upper(),
            'subject':     m.subject,
            'content':     (m.content or '')[:200],
            'is_hidden':   m.is_hidden,
            'likes':       m.like_count,
            'comments':    m.comment_count,
            'views':       m.views,
            'time_ago':    _time_ago(m.created_at),
        } for m in materials],
        'active_posts':       materials.count(),
        'total_interactions': sum(m.like_count + m.comment_count for m in materials),
        'total_views':        materials.aggregate(v=Sum('views'))['v'] or 0,
        'trending_topics':    list(
            SharedMaterial.objects.values('subject')
            .annotate(c=Count('subject')).order_by('-c')
            .values_list('subject', flat=True)[:10]
        ),
    })


# ── ADMIN — AI CONTROLS ───────────────────────────────────────────────────────

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
def admin_ai(request):
    docs  = SummarizedDocument.objects.select_related('user').order_by('-created_at')
    total = docs.count()
    return render(request, 'main/admin/ai_controls.html', {
        'doc_list': [{
            'file_name': d.file_name,
            'username':  d.user.username,
            'time_ago':  _time_ago(d.created_at),
            'status':    'success',
            'subject':   d.subject or 'General',
        } for d in docs[:15]],
        'quality_list': [{
            'file_name':    d.file_name,
            'username':     d.user.username,
            'time_ago':     _time_ago(d.created_at),
            'subject':      d.subject or 'General',
            'accuracy':     _quality_score(d.summary_text),
            'completeness': _completeness(d.summary_text),
            'rating':       round((_quality_score(d.summary_text) + _completeness(d.summary_text)) / 20, 1),
        } for d in docs[:6]],
        'subject_breakdown': list(
            SummarizedDocument.objects.values('subject')
            .annotate(count=Count('id')).order_by('-count')[:6]
        ),
        'top_users':       list(
            SummarizedDocument.objects.values('user__username')
            .annotate(count=Count('id')).order_by('-count')[:5]
        ),
        'total_summaries': total,
        'success_rate':    '100' if total > 0 else '0',
        'error_rate':      '0',
        'avg_processing':  '—',
    })


# ── ADMIN — ANALYTICS ─────────────────────────────────────────────────────────

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
def admin_analytics(request):
    now      = timezone.now()
    week_ago = now - timedelta(days=7)

    completed_qs     = Task.objects.filter(completed=True, completed_at__isnull=False)
    total_tasks_week = Task.objects.filter(created_at__gte=week_ago).count()

    peak_hour_row = (
        completed_qs
        .annotate(hour=ExtractHour('completed_at'))
        .values('hour').annotate(count=Count('id')).order_by('-count').first()
    )
    if peak_hour_row:
        h = peak_hour_row['hour']
        peak_productivity = f'{_fmt_hour(h)} – {_fmt_hour(h + 3)}'
    else:
        peak_productivity = 'N/A'

    DAY_NAMES = {1: 'Sunday', 2: 'Monday', 3: 'Tuesday', 4: 'Wednesday', 5: 'Thursday', 6: 'Friday', 7: 'Saturday'}
    peak_day_row = (
        completed_qs
        .annotate(wday=ExtractWeekDay('completed_at'))
        .values('wday').annotate(count=Count('id')).order_by('-count').first()
    )
    most_productive_day = DAY_NAMES.get(peak_day_row['wday'], 'N/A') if peak_day_row else 'N/A'

    subject_qs     = Task.objects.values('subject').annotate(c=Count('id')).order_by('-c')[:7]
    subject_labels = [s['subject'] or 'General' for s in subject_qs]
    subject_counts = [s['c'] for s in subject_qs]

    WEEKDAY_MAP  = {2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 1: 6}
    HOUR_BUCKETS = [
        ('6 AM',  6,  8), ('9 AM',  9, 11), ('12 PM', 12, 14),
        ('3 PM',  15, 17), ('6 PM', 18, 20), ('9 PM',  21, 23), ('12 AM', 0, 2),
    ]
    heat_matrix = [[0] * len(HOUR_BUCKETS) for _ in range(7)]
    for row in Task.objects.annotate(hour=ExtractHour('created_at'), wday=ExtractWeekDay('created_at')).values('hour', 'wday').annotate(count=Count('id')):
        day_idx = WEEKDAY_MAP.get(row['wday'], 0)
        for b_idx, (_, h_start, h_end) in enumerate(HOUR_BUCKETS):
            if h_start <= row['hour'] <= h_end:
                heat_matrix[day_idx][b_idx] += row['count']
                break

    weekly_completed, weekly_assigned, week_day_labels = [], [], []
    for i in range(6, -1, -1):
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end   = day_start + timedelta(days=1)
        qs_day    = Task.objects.filter(created_at__gte=day_start, created_at__lt=day_end)
        weekly_assigned.append(qs_day.count())
        weekly_completed.append(qs_day.filter(completed=True).count())
        week_day_labels.append(day_start.strftime('%a'))

    return render(request, 'main/admin/analytics.html', {
        'total_tasks_week':       total_tasks_week,
        'peak_productivity':      peak_productivity,
        'most_productive_day':    most_productive_day,
        'subject_labels_json':    json.dumps(subject_labels),
        'subject_counts_json':    json.dumps(subject_counts),
        'heatmap_json':           json.dumps(heat_matrix),
        'weekly_day_labels_json': json.dumps(week_day_labels),
        'weekly_completed_json':  json.dumps(weekly_completed),
        'weekly_assigned_json':   json.dumps(weekly_assigned),
    })


# ── ADMIN — AUDIT LOGS ────────────────────────────────────────────────────────

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
def admin_audit(request):
    today           = date.today()
    new_users_today = User.objects.filter(date_joined__date=today).count()
    inactive_users  = User.objects.filter(is_active=False).count()

    security_logs = [
        {'icon': 'green', 'title': f'New user registered: {u.email}', 'by': u.email,
         'time': u.date_joined.strftime('%Y-%m-%d %H:%M:%S'), 'ip': '—', 'badge': 'success', 'badge_label': 'success'}
        for u in User.objects.filter(date_joined__date=today).order_by('-date_joined')[:5]
    ] + [
        {'icon': 'blue', 'title': f'Inactive account: {u.email}', 'by': 'admin',
         'time': u.date_joined.strftime('%Y-%m-%d %H:%M:%S'), 'ip': '—', 'badge': 'info', 'badge_label': 'info'}
        for u in User.objects.filter(is_active=False).order_by('-date_joined')[:3]
    ]
    if not security_logs:
        security_logs = [{'icon': 'blue', 'title': 'No new security events today.', 'by': 'system', 'time': '—', 'ip': '—', 'badge': 'info', 'badge_label': 'info'}]

    system_logs = [
        {'icon': 'green', 'title': f'Document summarized: {d.file_name}', 'by': d.user.username,
         'time': d.created_at.strftime('%Y-%m-%d %H:%M:%S'), 'badge': 'success', 'badge_label': 'success'}
        for d in SummarizedDocument.objects.select_related('user').order_by('-created_at')[:8]
    ]
    if not system_logs:
        system_logs = [{'icon': 'blue', 'title': 'No documents summarized yet.', 'by': 'System', 'time': '—', 'badge': 'info', 'badge_label': 'info'}]

    return render(request, 'main/admin/audit_logs.html', {
        'security_events': new_users_today + inactive_users,
        'warnings_today':  inactive_users,
        'avg_rating':      '0',
        'security_logs':   security_logs,
        'system_logs':     system_logs,
    })


# ── ADMIN — MODERATION (hide / delete posts) ──────────────────────────────────

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
@require_POST
def admin_hide_post(request, post_id):
    post   = get_object_or_404(SharedMaterial, id=post_id)
    data   = json.loads(request.body)
    action = data.get('action')

    if action == 'hide':
        post.is_hidden = True
        post.save()
        Notification.objects.create(
            user=post.author,
            message=(
                f'Your post "{post.title}" has been hidden by a moderator '
                f'because it may contain inappropriate content or violates our community guidelines.'
            ),
        )
    elif action == 'unhide':
        post.is_hidden = False
        post.save()
        Notification.objects.create(
            user=post.author,
            message=f'Your post "{post.title}" has been reviewed and is now visible again.',
        )
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid action'}, status=400)

    return JsonResponse({'status': 'success', 'is_hidden': post.is_hidden})


@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
def admin_delete_post(request, post_id):
    if request.method != 'DELETE':
        return JsonResponse({'status': 'error'}, status=405)
    post = get_object_or_404(SharedMaterial, id=post_id)
    Notification.objects.create(
        user=post.author,
        message=(
            f'Your post "{post.title}" has been permanently removed by a moderator '
            f'for violating our community guidelines. Please review our content policy.'
        ),
    )
    post.delete()
    return JsonResponse({'status': 'success'})


# ── USER — DASHBOARD ──────────────────────────────────────────────────────────

@login_required
@csrf_protect
def dashboard(request):
    if is_admin(request.user):
        return redirect('admin_dashboard')
    metrics       = calculate_user_metrics(request.user)
    today         = date.today()
    start_of_week = today - timedelta(days=today.weekday())

    upcoming_tasks_list = [{
        'title':    t.title,
        'date':     t.due_date.strftime('%b %d'),
        'priority': t.priority,
        'category': t.category,
        'daysLeft': max(0, (t.due_date - today).days),
    } for t in Task.objects.filter(user=request.user, completed=False).order_by('due_date')[:4]]

    daily_hours = [
        (Task.objects.filter(user=request.user, completed=True, created_at__date=start_of_week + timedelta(days=i)).count() * 2) +
        SummarizedDocument.objects.filter(user=request.user, created_at__date=start_of_week + timedelta(days=i)).count()
        for i in range(7)
    ]

    recent_summaries = SummarizedDocument.objects.filter(user=request.user).order_by('-created_at')[:5]
    summaries_list = [{
        'id':      s.id,
        'title':   s.file_name,
        'date':    s.created_at.strftime('%b %d'),
        'emoji':   s.emoji,
        'summary': s.summary_text[:100] + '...' if len(s.summary_text) > 100 else s.summary_text,
    } for s in recent_summaries]

    return render(request, 'main/dashboard.html', {
        **metrics,
        'upcoming_tasks_json':    json.dumps(upcoming_tasks_list),
        'recent_summaries_json':  json.dumps(summaries_list),
        'weekly_hours_list':      json.dumps(daily_hours),
        'schedule_items_json':    json.dumps([{
            'id': i.id, 'day': i.day, 'time': i.time, 'activity': i.activity, 'color': i.color,
        } for i in ScheduleItem.objects.filter(user=request.user)]),
    })


# ── USER — TASKS ──────────────────────────────────────────────────────────────

@login_required
def tasks_view(request):
    tasks_data = [{
        'id':        t.id,
        'title':     t.title,
        'subject':   t.subject,
        'category':  t.category,
        'priority':  t.priority,
        'dueDate':   t.due_date.strftime('%Y-%m-%d'),
        'completed': t.completed,
    } for t in Task.objects.filter(user=request.user)]
    return render(request, 'main/tasks.html', {'tasks_data': json.dumps(tasks_data)})


@login_required
@require_POST
@ratelimit(key='ip', rate='10/m', block=True)
def add_task(request):
    try:
        data = json.loads(request.body)

        title = data.get('title', '').strip()
        if not title or len(title) > 255:
            return JsonResponse({'status': 'error', 'message': 'Invalid title length.'}, status=400)
        priority = data.get('priority')
        if priority not in ('Low', 'Medium', 'High'):
            return JsonResponse({'status': 'error', 'message': 'Invalid priority.'}, status=400)
        due_date_str = data.get('dueDate', '')
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', due_date_str):
            return JsonResponse({'status': 'error', 'message': 'Invalid due date format.'}, status=400)

        task = Task.objects.create(
            user      = request.user,
            title     = title,
            subject   = str(data.get('subject', 'General'))[:100],
            category  = str(data.get('category', 'General'))[:20],
            priority  = priority,
            due_date  = datetime.strptime(due_date_str, '%Y-%m-%d').date(),
            completed = False,
        )
        return JsonResponse({'status': 'success', 'task': {
            'id': task.id, 'title': task.title, 'subject': task.subject,
            'category': task.category, 'priority': task.priority,
            'dueDate': task.due_date.strftime('%Y-%m-%d'), 'completed': task.completed,
        }})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def edit_task(request, task_id):
    try:
        data = json.loads(request.body)
        task = Task.objects.get(id=task_id, user=request.user)

        title = data.get('title', '').strip()
        if not title or len(title) > 255:
            return JsonResponse({'status': 'error', 'message': 'Invalid title length.'}, status=400)
        priority = data.get('priority')
        if priority not in ('Low', 'Medium', 'High'):
            return JsonResponse({'status': 'error', 'message': 'Invalid priority.'}, status=400)
        due_date_str = data.get('dueDate', '')
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', due_date_str):
            return JsonResponse({'status': 'error', 'message': 'Invalid date format.'}, status=400)

        task.title    = title
        task.subject  = str(data.get('subject', task.subject))[:100]
        task.category = str(data.get('category', task.category))[:20]
        task.priority = priority
        task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        task.save()
        return JsonResponse({'status': 'success', 'task': {
            'id': task.id, 'title': task.title, 'subject': task.subject,
            'category': task.category, 'priority': task.priority,
            'dueDate': task.due_date.strftime('%Y-%m-%d'), 'completed': task.completed,
        }})
    except Task.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Task not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def delete_task(request, task_id):
    try:
        Task.objects.get(id=task_id, user=request.user).delete()
        return JsonResponse({'status': 'success'})
    except Task.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Task not found'}, status=404)


@login_required
@require_POST
def toggle_task(request, task_id):
    try:
        task           = Task.objects.get(id=task_id, user=request.user)
        task.completed = not task.completed
        # Stamp completion time (drives peak-hour / most-productive-day analytics)
        task.completed_at = timezone.now() if task.completed else None
        task.save()
        return JsonResponse({'status': 'success', 'completed': task.completed})
    except Task.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Task not found'}, status=404)


# ── USER — UPLOAD / SUMMARIZE ─────────────────────────────────────────────────

@login_required
@csrf_protect
def upload(request):
    recent_summaries = SummarizedDocument.objects.filter(user=request.user).order_by('-created_at')[:10]
    summaries_list = [{
        'id':      s.id,
        'title':   s.file_name,
        'category': 'General',
        'date':    s.created_at.strftime('%b %d'),
        'emoji':   s.emoji,
        'summary': s.summary_text,
    } for s in recent_summaries]
    return render(request, 'main/upload.html', {'recent_summaries': summaries_list})


@login_required
@csrf_protect
@ratelimit(key='user', rate='20/m', method='POST', block=True)
def summarize_doc(request):
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)

        uploaded_file = request.FILES['file']
        file_name     = str(uploaded_file.name).strip()

        if uploaded_file.size > 15 * 1024 * 1024:
            return JsonResponse({'status': 'error', 'message': 'File size exceeds 15MB limit.'}, status=400)
        if not file_name or len(file_name) > 255:
            return JsonResponse({'status': 'error', 'message': 'File name invalid or too long.'}, status=400)
        if not file_name.lower().endswith(('.pdf', '.docx', '.pptx', '.txt')):
            return JsonResponse({'status': 'error', 'message': 'Unsupported file type.'}, status=400)

        import hashlib
        uploaded_file.seek(0)
        file_hash = hashlib.sha256(uploaded_file.read()).hexdigest()
        uploaded_file.seek(0)

        # Delegate extraction + summarization to service layer
        content = extract_text_from_file(uploaded_file)
        if not content:
            return JsonResponse({'status': 'error', 'message': 'Could not extract text from document.'}, status=400)

        final_summary, title_line = generate_document_summary(content, file_name)

        doc = SummarizedDocument.objects.create(
            user          = request.user,
            file_name     = bleach.clean(file_name),
            category      = 'General',
            summary_text  = final_summary,
            content_hash  = hashlib.sha256(final_summary.encode('utf-8')).hexdigest(),
            document_file = uploaded_file,
            emoji         = '📄',
        )
        AuditLog.objects.create(
            user    = request.user,
            action  = 'Summarized Document',
            details = f'File: {file_name}, Hash: {file_hash}',
        )
        return JsonResponse({'status': 'success', 'summary': final_summary, 'title': title_line, 'doc_id': doc.id})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
@require_POST
def summarize_batch(request):
    try:
        data    = json.loads(request.body)
        doc_ids = data.get('doc_ids', [])
        if not doc_ids:
            return JsonResponse({'status': 'error', 'message': 'No documents provided.'}, status=400)

        docs = SummarizedDocument.objects.filter(id__in=doc_ids, user=request.user)
        if not docs.exists():
            return JsonResponse({'status': 'error', 'message': 'Documents not found.'}, status=404)

        batch_output = generate_batch_synthesis(doc_ids, request.user)

        individual_summaries = ''.join(
            f'**📄 Document {i}: {d.file_name}**\n{d.summary_text}\n\n'
            for i, d in enumerate(docs, 1)
        )
        full_batch_summary = f'{individual_summaries}**🔄 --- Master AI Synthesis ---**\n\n{batch_output}'
        full_batch_summary = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', full_batch_summary)
        batch_output_html  = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', batch_output)

        batch_doc = SummarizedDocument.objects.create(
            user         = request.user,
            file_name    = f'Batch Summary ({docs.count()} Files)',
            summary_text = full_batch_summary,
            emoji        = '📊',
            category     = 'Batch',
        )
        return JsonResponse({
            'status':           'success',
            'combined_summary': batch_output_html,
            'full_summary':     full_batch_summary,
            'batch_doc_id':     batch_doc.id,
            'batch_title':      batch_doc.file_name,
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


# ── USER — COLLABORATE ────────────────────────────────────────────────────────

@login_required
@csrf_protect
def collaborate(request):
    materials             = SharedMaterial.objects.all().order_by('-created_at')
    total_community_likes = 0
    materials_list        = []

    for m in materials:
        m_likes = m.likes.count()
        total_community_likes += m_likes
        is_anon = m.is_anonymous
        materials_list.append({
            'id':             m.id,
            'title':          m.title,
            'author':         'Anonymous' if is_anon else m.author.username,
            'authorInitials': '??' if is_anon else m.author.username[:2].upper(),
            'authorColor':    '#9CA3AF' if is_anon else ('#8C1007' if m.author == request.user else '#4B5563'),
            'is_anonymous':   is_anon,
            'is_mine':        m.author == request.user,
            'category':       m.category,
            'subject':        m.subject,
            'preview':        m.content,
            'likes':          m_likes,
            'views':          m.views,
            'comments':       m.comments.count(),
            'timeAgo':        'Just now',
            'emoji':          m.emoji,
            'liked':          m.likes.filter(id=request.user.id).exists(),
            'tags':           [m.subject],
            'file_url':       m.file.url if m.file else None,
        })

    # Top contributors (points-based)
    contributors = []
    for u in User.objects.all():
        material_count  = SharedMaterial.objects.filter(author=u).count()
        likes_received  = SharedMaterial.objects.filter(author=u).aggregate(total=Count('likes'))['total'] or 0
        comment_count   = Comment.objects.filter(author=u).count()
        completed_tasks = Task.objects.filter(user=u, completed=True).count()
        points = (material_count * 10) + (likes_received * 5) + (comment_count * 2) + completed_tasks
        if points > 0:
            contributors.append({
                'username': u.username,
                'initials': u.username[:2].upper(),
                'points':   points,
                'materials': material_count,
            })
    contributors = sorted(contributors, key=lambda x: x['points'], reverse=True)[:5]

    return render(request, 'main/collaborate.html', {
        'materials_json':        json.dumps(materials_list),
        'active_students':       User.objects.count(),
        'total_community_likes': total_community_likes,
        'top_contributors':      contributors,
    })


@login_required
@require_POST
@ratelimit(key='ip', rate='10/m', block=True)
def share_material(request):
    try:
        title    = bleach.clean(request.POST.get('title', '').strip())
        subject  = bleach.clean(request.POST.get('subject', '').strip())
        category = bleach.clean(request.POST.get('category', 'General').strip())
        content  = bleach.clean(request.POST.get('preview', '').strip())
        is_anon  = request.POST.get('is_anonymous') == 'true'
        file_obj = request.FILES.get('file')

        if not title or len(title) > 255:
            return JsonResponse({'status': 'error', 'message': 'Title length invalid.'}, status=400)
        if len(subject) > 100:
            return JsonResponse({'status': 'error', 'message': 'Subject too long.'}, status=400)
        if len(category) > 20:
            return JsonResponse({'status': 'error', 'message': 'Category too long.'}, status=400)
        if not content:
            return JsonResponse({'status': 'error', 'message': 'Content missing.'}, status=400)

        material = SharedMaterial.objects.create(
            author       = request.user,
            title        = title,
            subject      = subject,
            category     = category,
            content      = content,
            file         = file_obj,
            is_anonymous = is_anon,
            emoji        = '📄',
        )
        AuditLog.objects.create(
            user    = request.user,
            action  = 'Shared Material',
            details = f'Title: {title}',
        )
        return JsonResponse({'status': 'success', 'material': {
            'id':             material.id,
            'title':          material.title,
            'author':         'Anonymous' if is_anon else material.author.username,
            'authorInitials': '??' if is_anon else material.author.username[:2].upper(),
            'authorColor':    '#9CA3AF' if is_anon else '#8C1007',
            'is_anonymous':   is_anon,
            'is_mine':        True,
            'category':       material.category,
            'subject':        material.subject,
            'preview':        material.content,
            'likes': 0, 'views': 0, 'comments': 0,
            'timeAgo': 'Just now',
            'emoji':   material.emoji,
            'liked':   False,
            'tags':    [material.subject],
            'file_url': material.file.url if material.file else None,
        }})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def toggle_like_material(request, material_id):
    material = get_object_or_404(SharedMaterial, id=material_id)
    if material.likes.filter(id=request.user.id).exists():
        material.likes.remove(request.user)
        liked = False
    else:
        material.likes.add(request.user)
        liked = True
    return JsonResponse({'status': 'success', 'liked': liked, 'likes_count': material.likes.count()})


@login_required
def get_material_comments(request, material_id):
    material = get_object_or_404(SharedMaterial, id=material_id)
    return JsonResponse({'status': 'success', 'comments': [{
        'id':             c.id,
        'author':         c.author.username,
        'authorInitials': c.author.username[:2].upper(),
        'authorColor':    '#8C1007' if c.author == request.user else '#4B5563',
        'text':           c.text,
        'timeAgo':        'Just now',
    } for c in material.comments.all().order_by('-created_at')]})


@login_required
@require_POST
@ratelimit(key='ip', rate='20/m', block=True)
def add_comment(request, material_id):
    try:
        material = get_object_or_404(SharedMaterial, id=int(material_id))
        text     = bleach.clean(str(json.loads(request.body).get('text', '')).strip())
        if not text:
            return JsonResponse({'status': 'error', 'message': 'Comment text required.'}, status=400)
        comment = Comment.objects.create(material=material, author=request.user, text=text)
        AuditLog.objects.create(
            user    = request.user,
            action  = 'Added Comment',
            details = f'Material ID: {material.id}',
        )
        return JsonResponse({'status': 'success', 'comment': {
            'id':             comment.id,
            'author':         comment.author.username,
            'authorInitials': comment.author.username[:2].upper(),
            'authorColor':    '#8C1007',
            'text':           comment.text,
            'timeAgo':        'Just now',
        }})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# ── USER — PROGRESS ───────────────────────────────────────────────────────────

@login_required
@csrf_protect
def progress(request):
    metrics = calculate_user_metrics(request.user)
    return render(request, 'main/progress.html', {
        **metrics,
        'category_stats_json': json.dumps([{
            'category': 'General Progress',
            'completed': metrics['completed_count'],
            'total':     metrics['total_tasks'],
        }]),
        'subject_labels_json': json.dumps(metrics.get('subject_labels', [])),
        'subject_data_json':   json.dumps(metrics.get('subject_data', [])),
        'weekly_hours_json':   json.dumps(metrics.get('weekly_hours_trend', [])),
    })


# ── USER — PROFILE ────────────────────────────────────────────────────────────

@login_required
@csrf_protect
def profile(request):
    profile_obj, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        new_username = request.POST.get('username', '').strip()
        if not new_username:
            messages.error(request, 'Username cannot be empty.')
        elif new_username == request.user.username:
            messages.info(request, 'No changes made.')
        elif User.objects.filter(username=new_username).exists():
            messages.error(request, 'Username already taken.')
        elif not re.match(r'^[a-zA-Z0-9_\.\-]{3,150}$', new_username):
            messages.error(request, 'Invalid username format. (3–150 chars, letters, numbers, dots, dashes, underscores)')
        else:
            old_un = request.user.username
            request.user.username = new_username
            request.user.save()
            AuditLog.objects.create(
                user    = request.user,
                action  = 'Username Updated',
                details = f'Changed from {old_un} to {new_username}',
            )
            messages.success(request, f'Username updated to {new_username} successfully!')
            return redirect('profile')

    metrics = calculate_user_metrics(request.user)
    return render(request, 'main/profile.html', {
        **metrics,
        'mfa_enabled':      profile_obj.totp_enabled,
        'recent_summaries': SummarizedDocument.objects.filter(user=request.user).order_by('-created_at')[:5],
    })


@login_required
@require_POST
def toggle_mfa(request):
    profile_obj, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.POST.get('action') == 'disable':
        profile_obj.totp_enabled = False
        profile_obj.save()
        send_security_alert(
            request.user,
            'MFA Disabled',
            'Multi-Factor Authentication (MFA) has been disabled for your account. '
            'Your account is now less secure against unauthorized access.',
        )
        AuditLog.objects.create(
            user    = request.user,
            action  = 'MFA Disabled',
            details = 'User manually disabled TOTP MFA',
        )
        messages.warning(request, 'MFA has been disabled. We strongly recommend re-enabling it.')
    return redirect('profile')


# ── USER — SCHEDULE ───────────────────────────────────────────────────────────

@login_required
@require_POST
def add_schedule_item(request):
    try:
        data     = json.loads(request.body)
        date_str = data.get('date')
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None
        item     = ScheduleItem.objects.create(
            user     = request.user,
            day      = data.get('day', 'General'),
            date     = date_obj,
            time     = data.get('time'),
            activity = data.get('activity'),
            color    = data.get('color', 'blue'),
        )
        return JsonResponse({'status': 'success', 'item': {
            'id': item.id, 'day': item.day,
            'date': item.date.strftime('%Y-%m-%d') if item.date else None,
            'time': item.time, 'activity': item.activity, 'color': item.color,
        }})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def delete_schedule_item(request, item_id):
    get_object_or_404(ScheduleItem, id=item_id, user=request.user).delete()
    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def edit_schedule_item(request, item_id):
    try:
        item     = get_object_or_404(ScheduleItem, id=item_id, user=request.user)
        data     = json.loads(request.body)
        date_str = data.get('date')
        if date_str:
            item.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        item.day      = data.get('day', item.day)
        item.time     = data.get('time', item.time)
        item.activity = data.get('activity', item.activity)
        item.color    = data.get('color', item.color)
        item.save()
        return JsonResponse({'status': 'success', 'item': {
            'id': item.id, 'day': item.day,
            'date': item.date.strftime('%Y-%m-%d') if item.date else None,
            'time': item.time, 'activity': item.activity, 'color': item.color,
        }})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# ── USER — PDF DOWNLOADS ──────────────────────────────────────────────────────

@login_required
def download_summary_pdf(request, doc_id):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    doc_obj = get_object_or_404(SummarizedDocument, id=doc_id, user=request.user)
    buffer  = io.BytesIO()
    pdf_doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    styles  = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'TitleStyle', parent=styles['Heading1'],
        fontSize=24, textColor=colors.HexColor('#8C1007'),
        alignment=1, spaceAfter=20, fontName='Helvetica-Bold',
    )
    body_style = ParagraphStyle(
        'BodyStyle', parent=styles['Normal'],
        fontSize=11, leading=14, fontName='Helvetica', alignment=4,
    )

    emo_regex    = r'[\U00010000-\U0010ffff]'
    clean_title  = re.sub(emo_regex, '', os.path.splitext(doc_obj.file_name)[0]).strip()
    text_content = re.sub(emo_regex, '', doc_obj.summary_text)
    text_content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text_content)

    def safe_text(txt):
        return re.sub(r'[^\x00-\xff\u2013\u2014\u2018\u2019\u201c\u201d\u2022]', '', txt or '')

    try:
        elements = [
            Paragraph(f'<b>Study Reviewer: {safe_text(clean_title)}</b>', title_style),
            Spacer(1, 25),
        ]
        for p_text in text_content.split('\n'):
            p_text = safe_text(p_text.strip())
            if not p_text:
                continue
            p_text = p_text.replace('<', '&lt;').replace('>', '&gt;')
            p_text = p_text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
            if p_text.startswith(('- ', '* ', '• ')) or re.match(r'^\d+\.', p_text):
                lst = ParagraphStyle('ListStyle', parent=body_style, leftIndent=25, bulletIndent=10, spaceAfter=8)
                elements.append(Paragraph(p_text, lst))
            else:
                elements.append(Paragraph(p_text, body_style))
                elements.append(Spacer(1, 10))

        pdf_doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()

        AuditLog.objects.create(
            user    = request.user,
            action  = 'Downloaded PDF Summary',
            details = f'Document ID: {doc_id}',
        )
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition']  = f'attachment; filename="Summary_{doc_id}.pdf"'
        response['Cache-Control']        = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    except Exception as e:
        print(f'CRITICAL PDF GEN ERROR: {e}')
        response = HttpResponse(doc_obj.summary_text, content_type='text/plain')
        response['Content-Disposition'] = f'attachment; filename="Summary_{doc_id}.txt"'
        return response


@login_required
def download_shared_pdf(request, material_id):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    material = get_object_or_404(SharedMaterial, id=material_id)
    buffer   = io.BytesIO()
    pdf_doc  = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    styles   = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'TitleStyle', parent=styles['Heading1'],
        fontSize=22, textColor=colors.HexColor('#8C1007'),
        alignment=1, spaceAfter=20, fontName='Helvetica-Bold',
    )
    body_style = ParagraphStyle(
        'BodyStyle', parent=styles['Normal'],
        fontSize=11, leading=14, fontName='Helvetica', alignment=4,
    )

    emo_regex    = r'[\U00010000-\U0010ffff]'
    clean_title  = re.sub(emo_regex, '', material.title).strip()
    text_content = re.sub(emo_regex, '', material.content)
    text_content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text_content)

    def safe_text(txt):
        return re.sub(r'[^\x00-\xff\u2013\u2014\u2018\u2019\u201c\u201d\u2022]', '', txt or '')

    try:
        elements = [
            Paragraph(f'<b>Community Resource: {safe_text(clean_title)}</b>', title_style),
            Paragraph(
                f'Shared by: {material.author.username if not material.is_anonymous else "Anonymous"}',
                styles['Italic'],
            ),
            Spacer(1, 20),
        ]
        for p_text in text_content.split('\n'):
            p_text = safe_text(p_text.strip())
            if not p_text:
                continue
            p_text = p_text.replace('<', '&lt;').replace('>', '&gt;')
            p_text = p_text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
            if p_text.startswith(('- ', '* ')) or re.match(r'^\d+\.', p_text):
                lst = ParagraphStyle('ListStyle', parent=body_style, leftIndent=25, bulletIndent=10, spaceAfter=8)
                elements.append(Paragraph(p_text, lst))
            else:
                elements.append(Paragraph(p_text, body_style))
                elements.append(Spacer(1, 10))

        pdf_doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Shared_{material_id}.pdf"'
        return response

    except Exception as e:
        print(f'SHARED PDF GEN ERROR: {e}')
        response = HttpResponse(material.content, content_type='text/plain')
        response['Content-Disposition'] = f'attachment; filename="Shared_{material_id}.txt"'
        return response


# ── USER — SEARCH ─────────────────────────────────────────────────────────────

@login_required
def search_documents(request):
    results = search_summarized_documents(request.user, request.GET.get('q', ''))
    return JsonResponse({'status': 'success', 'results': [{
        'id':      r.id,
        'title':   r.file_name,
        'summary': r.summary_text[:200] + '...',
        'emoji':   r.emoji,
        'date':    r.created_at.strftime('%Y-%m-%d'),
    } for r in results]})


# ── USER — NOTIFICATIONS ──────────────────────────────────────────────────────

@login_required
def notifications_view(request):
    notifs = Notification.objects.filter(user=request.user).order_by('-created_at')
    notifs.filter(is_read=False).update(is_read=True)
    return render(request, 'main/notifications.html', {'notifications': notifs})


# ── ADMIN — USER ACTIONS ──────────────────────────────────────────────────────

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
def admin_user_profile(request, user_id):
    u = get_object_or_404(User, id=user_id)
    p, _ = UserProfile.objects.get_or_create(user=u)
    return JsonResponse({
        'full_name':   u.get_full_name() or u.username,
        'username':    u.username,
        'email':       u.email,
        'date_joined': u.date_joined.strftime('%Y-%m-%d'),
        'major':       p.major,
        'streak':      p.streak,
        'is_active':   u.is_active,
        'is_staff':    u.is_staff,
    })

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
@require_POST
def admin_send_email(request, user_id):
    u    = get_object_or_404(User, id=user_id)
    data = json.loads(request.body)
    sub  = data.get('subject', 'Message from StudyOptimizer Admin')
    msg  = data.get('message', '')
    try:
        send_mail(sub, msg, settings.DEFAULT_FROM_EMAIL, [u.email], fail_silently=False)
        Notification.objects.create(user=u, message=f"Admin sent you an email: {sub}")
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'error'}, status=500)

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
@require_POST
def admin_toggle_account(request, user_id):
    u = get_object_or_404(User, id=user_id)
    if u.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'Cannot disable superuser'}, status=403)
    u.is_active = not u.is_active
    u.save()
    action = 'enabled' if u.is_active else 'disabled'
    Notification.objects.create(user=u, message=f"Your account has been {action} by an administrator.")
    return JsonResponse({'status': 'ok', 'is_active': u.is_active, 'action': action})

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
@require_POST
def admin_reset_pw(request, user_id):
    u = get_object_or_404(User, id=user_id)
    # Placeholder for real password reset link
    Notification.objects.create(user=u, message="An administrator has initiated a password reset for your account.")
    return JsonResponse({'status': 'ok'})

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
@require_POST
def admin_grant_admin(request, user_id):
    u = get_object_or_404(User, id=user_id)
    if u == request.user:
        return JsonResponse({'status': 'error', 'message': 'Cannot modify own admin status'}, status=403)
    u.is_staff = not u.is_staff
    u.save()
    action = 'granted' if u.is_staff else 'revoked'
    Notification.objects.create(user=u, message=f"Administrator access has been {action} for your account.")
    return JsonResponse({'status': 'ok', 'is_staff': u.is_staff, 'action': action})

@login_required(login_url='login')
@user_passes_test(is_admin, login_url='login')
@require_POST
def admin_delete_user(request, user_id):
    u = get_object_or_404(User, id=user_id)
    if u.is_superuser or u == request.user:
        return JsonResponse({'status': 'error', 'message': 'Cannot delete superuser/self'}, status=403)
    name = u.username
    u.delete()
    return JsonResponse({'status': 'ok', 'deleted_name': name})