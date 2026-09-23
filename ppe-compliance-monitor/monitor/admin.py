from django.contrib import admin
from .models import Violation, DetectionSession, IPCamera, CameraZone, CameraHealthLog, AuditLog

@admin.register(CameraZone)
class CameraZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "is_critical", "camera_count", "created_at")
    list_filter = ("is_critical",)
    search_fields = ("name",)
    def camera_count(self, obj):
        return obj.cameras.count()
    camera_count.short_description = "Cameras"

@admin.register(IPCamera)
class IPCameraAdmin(admin.ModelAdmin):
    list_display = ("name","zone","ip_address","port","protocol","location","is_active","detection_enabled","status","uptime_24h","consecutive_failures","last_seen","created_at")
    list_filter = ("protocol","is_active","detection_enabled","status","zone")
    search_fields = ("name","ip_address","location","zone__name")
    list_editable = ("is_active","detection_enabled")
    readonly_fields = ("status","last_seen","last_error","consecutive_failures","uptime_24h","created_at","updated_at","created_by","updated_by")
    fieldsets = (
        ("Identity", {"fields": ("name","zone","ip_address","port","protocol","stream_path","location","description")}),
        ("Auth (encrypted at rest if PPE_FERNET_KEY set)", {"fields": ("username","password")}),
        ("Operation", {"fields": ("is_active","detection_enabled","confidence_threshold")}),
        ("Health (auto)", {"fields": ("status","last_seen","last_error","consecutive_failures","uptime_24h")}),
        ("Audit", {"fields": ("created_at","updated_at","created_by","updated_by")}),
    )
    actions = ["mark_active", "mark_inactive", "test_selected"]
    def mark_active(self, request, queryset):
        queryset.update(is_active=True, status="unknown")
    mark_active.short_description = "Mark selected as active"
    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False, status="inactive")
    mark_inactive.short_description = "Mark selected as inactive"
    def test_selected(self, request, queryset):
        ok = 0
        for cam in queryset:
            success, _ = cam.test_connection(timeout=3)
            ok += 1 if success else 0
        self.message_user(request, f"Tested {queryset.count()} cameras: {ok} OK")
    test_selected.short_description = "Test connection"

@admin.register(CameraHealthLog)
class CameraHealthLogAdmin(admin.ModelAdmin):
    list_display = ("camera","checked_at","is_ok","latency_ms","message")
    list_filter = ("is_ok","checked_at","camera__zone")
    search_fields = ("camera__name","camera__ip_address")
    date_hierarchy = "checked_at"
    readonly_fields = ("camera","checked_at","is_ok","latency_ms","message")

@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
    list_display = ("timestamp","person_id","camera","zone","violation_type","missing_items_display","duration","resolution_time")
    list_filter = ("violation_type","timestamp","camera","zone")
    search_fields = ("person_id","camera__name","camera__ip_address","zone__name")
    readonly_fields = ("created_at",)
    date_hierarchy = "timestamp"
    list_select_related = ("camera","zone")

@admin.register(DetectionSession)
class DetectionSessionAdmin(admin.ModelAdmin):
    list_display = ("id","session_type","camera","created_at","person_count","violation_count","compliant_count","processing_time_ms")
    list_filter = ("session_type","created_at","camera")
    search_fields = ("camera__name",)

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp","user","action","entity","entity_id","ip_address")
    list_filter = ("action","entity","timestamp")
    search_fields = ("entity_id","user__username")
    readonly_fields = ("timestamp","user","action","entity","entity_id","detail","ip_address")
    date_hierarchy = "timestamp"
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
