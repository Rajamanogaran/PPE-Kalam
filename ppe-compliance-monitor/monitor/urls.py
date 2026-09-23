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
    # IP Cameras
    path('cameras/', views.ip_camera_list, name='camera_list'),
    path('cameras/add/', views.ip_camera_create, name='camera_add'),
    path('cameras/<int:pk>/edit/', views.ip_camera_edit, name='camera_edit'),
    path('cameras/<int:pk>/delete/', views.ip_camera_delete, name='camera_delete'),
    path('cameras/<int:pk>/toggle/', views.ip_camera_toggle, name='camera_toggle'),
    path('cameras/<int:pk>/test/', views.ip_camera_test, name='camera_test'),
    path('cameras/<int:pk>/snapshot/', views.ip_camera_snapshot, name='camera_snapshot'),
    path('cameras/<int:pk>/stream/', views.ip_camera_stream, name='camera_stream'),
    path('cameras/bulk-add/', views.ip_camera_bulk_add, name='camera_bulk_add'),

    # APIs
    path('api/health/', views.api_health, name='api_health'),
    path('api/process-frame/', views.api_process_frame, name='api_process_frame'),
    path('api/detect-image/', views.api_detect_image, name='api_detect_image'),
    path('api/stats/', views.api_stats, name='api_stats'),
    path('api/violations/', views.api_violations, name='api_violations'),
    path('api/video-feed/', views.video_feed, name='video_feed'),
    path('api/export-csv/', views.export_violations_csv, name='export_csv'),
    path('api/cameras/', views.api_camera_list, name='api_camera_list'),
    path('api/cameras/<int:pk>/', views.api_camera_detail, name='api_camera_detail'),
]
