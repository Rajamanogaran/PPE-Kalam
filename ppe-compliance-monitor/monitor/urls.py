from django.urls import path
from . import views

app_name = 'monitor'

urlpatterns = [
    # Pages
    path('', views.index, name='index'),
    path('live/', views.live_monitor, name='live'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('violations/', views.violations_log, name='violations'),
    path('upload/', views.upload_view, name='upload'),

    # APIs
    path('api/health/', views.api_health, name='api_health'),
    path('api/process-frame/', views.api_process_frame, name='api_process_frame'),
    path('api/detect-image/', views.api_detect_image, name='api_detect_image'),
    path('api/stats/', views.api_stats, name='api_stats'),
    path('api/violations/', views.api_violations, name='api_violations'),
    path('api/video-feed/', views.video_feed, name='video_feed'),
    path('api/export-csv/', views.export_violations_csv, name='export_csv'),
]
