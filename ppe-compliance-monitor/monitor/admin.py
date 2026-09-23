from django.contrib import admin
from .models import Violation, DetectionSession, IPCamera

@admin.register(IPCamera)
class IPCameraAdmin(admin.ModelAdmin):
    list_display = ('name','ip_address','port','protocol','location','is_active','detection_enabled','status','last_seen','created_at')
    list_filter = ('protocol','is_active','detection_enabled','status')
    search_fields = ('name','ip_address','location')
    list_editable = ('is_active','detection_enabled')
    readonly_fields = ('status','last_seen','last_error','created_at','updated_at')
    fieldsets = (
        ('Camera', {'fields': ('name','ip_address','port','protocol','stream_path','location','description')}),
        ('Auth', {'fields': ('username','password')}),
        ('Settings', {'fields': ('is_active','detection_enabled','confidence_threshold')}),
        ('Status', {'fields': ('status','last_seen','last_error','created_at','updated_at')}),
    )

@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
    list_display = ('timestamp','person_id','camera','violation_type','missing_items_display','duration','resolution_time')
    list_filter = ('violation_type','timestamp','camera')
    search_fields = ('person_id','camera__name','camera__ip_address')
    readonly_fields = ('created_at',)
    date_hierarchy = 'timestamp'

@admin.register(DetectionSession)
class DetectionSessionAdmin(admin.ModelAdmin):
    list_display = ('id','session_type','created_at','person_count','violation_count','compliant_count','processing_time_ms')
    list_filter = ('session_type','created_at')
