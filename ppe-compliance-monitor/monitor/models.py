from django.db import models
from django.utils import timezone
import json

class IPCamera(models.Model):
    PROTOCOL_CHOICES = [
        ('rtsp', 'RTSP'),
        ('rtsp_tcp', 'RTSP/TCP'),
        ('http', 'HTTP/MJPEG'),
        ('https', 'HTTPS'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('error', 'Connection Error'),
        ('unknown', 'Unknown'),
    ]

    name = models.CharField(max_length=100, help_text="Display name, e.g., Gate-01, Workshop-Floor")
    ip_address = models.GenericIPAddressField(protocol='both', help_text="Camera IP, e.g., 192.168.1.64")
    port = models.PositiveIntegerField(default=554, help_text="Port: 554 for RTSP, 80/8080 for HTTP")
    protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES, default='rtsp')
    stream_path = models.CharField(max_length=300, default="/stream1", help_text="Path after IP:port, e.g., /stream1, /live/ch1, /video.mjpg")
    username = models.CharField(max_length=100, blank=True, help_text="RTSP/HTTP auth user (optional)")
    password = models.CharField(max_length=100, blank=True, help_text="Password (optional, stored plain - use secrets in prod)")
    location = models.CharField(max_length=200, blank=True, help_text="Physical location / zone")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, help_text="Enable/disable this camera")
    detection_enabled = models.BooleanField(default=True, help_text="Run PPE detection on this stream")
    confidence_threshold = models.FloatField(default=0.6, help_text="YOLO confidence for this camera")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='unknown')
    last_seen = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', 'name']
        verbose_name = "IP Camera"
        verbose_name_plural = "IP Cameras"
        unique_together = [('ip_address', 'port', 'stream_path')]

    def __str__(self):
        return f"{self.name} ({self.ip_address}:{self.port})"

    @property
    def stream_url(self) -> str:
        """Build full stream URL including auth if provided"""
        auth = f"{self.username}:{self.password}@" if self.username else ""
        # handle http vs rtsp formatting
        if self.protocol in ('http', 'https'):
            return f"{self.protocol}://{auth}{self.ip_address}:{self.port}{self.stream_path}"
        elif self.protocol == 'rtsp_tcp':
            # opencv uses rtsp with tcp transport via env var, but url is still rtsp://
            return f"rtsp://{auth}{self.ip_address}:{self.port}{self.stream_path}"
        else:
            return f"rtsp://{auth}{self.ip_address}:{self.port}{self.stream_path}"

    @property
    def display_url(self) -> str:
        """Masked URL for UI (hide password)"""
        auth = f"{self.username}:****@" if self.password else (f"{self.username}@" if self.username else "")
        proto = 'rtsp' if self.protocol == 'rtsp_tcp' else self.protocol
        return f"{proto}://{auth}{self.ip_address}:{self.port}{self.stream_path}"

    def test_connection(self, timeout: int = 5) -> tuple[bool, str]:
        """Try to open stream with cv2.VideoCapture for a single frame"""
        try:
            import cv2
        except ImportError:
            return False, "OpenCV not installed"
        try:
            # For RTSP over TCP, set ffmpeg option
            if self.protocol == 'rtsp_tcp':
                import os
                os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'
            cap = cv2.VideoCapture(self.stream_url)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout * 1000)
            if not cap.isOpened():
                return False, "Cannot open stream (check IP/port/path/auth)"
            ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                return False, "Opened but no frame received"
            return True, f"OK - {frame.shape[1]}x{frame.shape[0]}"
        except Exception as e:
            return False, str(e)

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
    camera = models.ForeignKey(IPCamera, null=True, blank=True, on_delete=models.SET_NULL, related_name='violations', help_text="Camera that captured this violation")
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
