from django.urls import path
from . import views
from django.contrib.auth.views import LogoutView


urlpatterns = [
    path('', views.index, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('mfa_verify/', views.mfa_verify, name='mfa_verify'),
    path('setup_totp/', views.setup_totp, name='setup_totp'),
    path('google-login/', views.google_login, name='google_login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('progress/', views.progress, name='progress'),
    path('upload/', views.upload, name='upload'),
    path('tasks/', views.tasks_view, name='tasks'),
    path('tasks/add/', views.add_task, name='add_task'),
    path('tasks/edit/<int:task_id>/', views.edit_task, name='edit_task'),
    path('tasks/delete/<int:task_id>/', views.delete_task, name='delete_task'),
    path('tasks/toggle/<int:task_id>/', views.toggle_task, name='toggle_task'),
    path('summarize/', views.summarize_doc, name='summarize_doc'),
    path('summarize_batch/', views.summarize_batch, name='summarize_batch'),
    path('summarize/download/<int:doc_id>/', views.download_summary_pdf, name='download_summary_pdf'),
    path('collaborate/', views.collaborate, name='collaborate'),
    path('collaborate/share/', views.share_material, name='share_material'),
    path('collaborate/like/<int:material_id>/', views.toggle_like_material, name='like_material'),
    path('collaborate/comments/<int:material_id>/', views.get_material_comments, name='get_comments'),
    path('collaborate/comments/<int:material_id>/add/', views.add_comment, name='add_comment'),
    path('collaborate/download/<int:material_id>/', views.download_shared_pdf, name='download_shared_pdf'),
    path('collaborate/view/<int:material_id>/', views.view_shared_file, name='view_shared_file'),
    path('tasks/schedule/add/', views.add_schedule_item, name='add_schedule'),
    path('tasks/schedule/edit/<int:item_id>/', views.edit_schedule_item, name='edit_schedule'),
    path('tasks/schedule/delete/<int:item_id>/', views.delete_schedule_item, name='delete_schedule'),
    path('profile/', views.profile, name='profile'),
    path('profile/mfa/toggle/', views.toggle_mfa, name='toggle_mfa'),
    path('search/', views.search_documents, name='search_documents'),
    path('admin-panel/',                views.admin_dashboard,    name='admin_dashboard'),
    path('admin-panel/users/',          views.admin_users,        name='admin_users'),
    path('admin-panel/collaboration/',  views.admin_collaboration, name='admin_collaboration'),
    path('admin-panel/ai/',             views.admin_ai,            name='admin_ai'),
    path('admin-panel/analytics/',      views.admin_analytics,     name='admin_analytics'),
    path('admin-panel/audit-logs/',     views.admin_audit,         name='admin_audit'),

    # Admin Post Controls
    path('admin-panel/posts/<int:post_id>/hide/',   views.admin_hide_post,   name='admin_hide_post'),
    path('admin-panel/posts/<int:post_id>/delete/', views.admin_delete_post, name='admin_delete_post'),
    path('admin/tags/add/',                         views.admin_add_tag,     name='admin_add_tag'),

    # Admin User Actions
    path('admin-panel/users/<int:user_id>/profile/',    views.admin_user_profile,  name='admin_user_profile'),
    path('admin-panel/users/<int:user_id>/disable/',    views.admin_toggle_account, name='admin_toggle_account'),
    path('admin-panel/users/<int:user_id>/grant-admin/', views.admin_grant_admin,  name='admin_grant_admin'),
    path('admin-panel/users/<int:user_id>/delete/',     views.admin_delete_user,   name='admin_delete_user'),

    # User Features (Helpful)
    path('collaborate/helpful/<int:material_id>/', views.toggle_helpful_material, name='helpful_material'),
]