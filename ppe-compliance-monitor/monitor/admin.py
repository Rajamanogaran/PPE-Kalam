from django.contrib import admin
from .models import Violation, DetectionSession

@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
    list_display = ('timestamp','person_id','violation_type','missing_items_display','duration','resolution_time')
    list_filter = ('violation_type','timestamp')
    search_fields = ('person_id',)
    readonly_fields = ('created_at',)
    date_hierarchy = 'timestamp'

@admin.register(DetectionSession)
class DetectionSessionAdmin(admin.ModelAdmin):
    list_display = ('id','session_type','created_at','person_count','violation_count','compliant_count','processing_time_ms')
    list_filter = ('session_type','created_at')
