from django.db import models
from django.utils import timezone
import json

class Violation(models.Model):
    VIOLATION_CHOICES = [
        ('DETECTED', 'Detected'),
        ('RESOLVED', 'Resolved'),
    ]

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    person_id = models.CharField(max_length=64, db_index=True)
    missing_items = models.JSONField(default=list, help_text="List of missing PPE items")
    violation_type = models.CharField(max_length=10, choices=VIOLATION_CHOICES, default='DETECTED')
    duration = models.FloatField(null=True, blank=True, help_text="Duration in seconds if resolved")
    resolution_time = models.DateTimeField(null=True, blank=True)
    image = models.ImageField(upload_to='violations/%Y/%m/%d/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "PPE Violation"
        verbose_name_plural = "PPE Violations"

    def __str__(self):
        return f"Violation {self.person_id} @ {self.timestamp:%Y-%m-%d %H:%M:%S} - {self.violation_type}"

    @property
    def missing_items_display(self):
        if isinstance(self.missing_items, list):
            return ", ".join(self.missing_items)
        try:
            items = json.loads(self.missing_items)
            return ", ".join(items)
        except:
            return str(self.missing_items)


class DetectionSession(models.Model):
    """Track an upload / live session for analytics"""
    created_at = models.DateTimeField(auto_now_add=True)
    session_type = models.CharField(max_length=20, choices=[('image','Image'),('video','Video'),('live','Live')], default='image')
    file = models.FileField(upload_to='sessions/%Y/%m/%d/', null=True, blank=True)
    person_count = models.IntegerField(default=0)
    violation_count = models.IntegerField(default=0)
    compliant_count = models.IntegerField(default=0)
    processing_time_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.session_type} session {self.id} - {self.created_at:%H:%M:%S}"
