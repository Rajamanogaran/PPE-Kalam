from django.db import models, IntegrityError
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.core.exceptions import ValidationError
import json
import logging
import ipaddress

logger = logging.getLogger(__name__)

# --- Encryption helper for camera passwords (Fernet if key configured, else plain with warning) ---
def _get_fernet():
    try:
        from django.conf import settings
        key = getattr(settings, "PPE_FERNET_KEY", "")
        if not key:
            return None
        from cryptography.fernet import Fernet  # type: ignore
        # Key must be 32 url-safe base64; if not valid, Fernet will raise
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        logger.warning(f"Fernet not available or invalid key: {e}")
        return None

def encrypt_value(plain: str) -> str:
    if not plain:
        return ""
    f = _get_fernet()
    if f:
        try:
            return "enc$" + f.encrypt(plain.encode()).decode()
        except Exception as e:
            logger.warning(f"encrypt failed, storing plain: {e}")
    return plain

def decrypt_value(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("enc$"):
        f = _get_fernet()
        if f:
            try:
                return f.decrypt(stored[4:].encode()).decode()
            except Exception as e:
                logger.warning(f"decrypt failed: {e}")
                return ""
        return ""
    return stored

# --- Zone / Site grouping (industry: per-area compliance) ---
class CameraZone(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="e.g., Workshop A, Gate-1, Warehouse")
    description = models.TextField(blank=True)
    is_critical = models.BooleanField(default=False, help_text="Critical zone: violations trigger immediate alert")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Camera Zone"
        verbose_name_plural = "Camera Zones"

    def __str__(self):
        return self.name

class IPCamera(models.Model):
    PROTOCOL_CHOICES = [
        ("rtsp", "RTSP"),
        ("rtsp_tcp", "RTSP/TCP (reliable)"),
        ("http", "HTTP/MJPEG"),
        ("https", "HTTPS/MJPEG"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("error", "Connection Error"),
        ("unknown", "Unknown"),
    ]

    # Core identity
    name = models.CharField(
        max_length=100,
        validators=[RegexValidator(r"^[\w\-\s]+$", "Use letters, numbers, -, _ and spaces")],
        help_text="Display name, e.g., Gate-01, Workshop-Floor",
    )
    zone = models.ForeignKey(CameraZone, null=True, blank=True, on_delete=models.SET_NULL, related_name="cameras", help_text="Zone for compliance grouping")
    ip_address = models.GenericIPAddressField(protocol="both", help_text="Camera IP, e.g., 192.168.1.64 (or hostname if GenericIPAddressField is bypassed via form)")
    port = models.PositiveIntegerField(
        default=554,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        help_text="Port: 554 for RTSP, 80/8080 for HTTP",
    )
    protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES, default="rtsp", db_index=True)
    stream_path = models.CharField(
        max_length=300,
        default="/stream1",
        validators=[RegexValidator(r"^/.*", "Must start with /")],
        help_text="Path after IP:port, e.g., /stream1, /live/ch1, /video.mjpg",
    )
    username = models.CharField(max_length=100, blank=True, help_text="RTSP/HTTP auth user (optional)")
    # Password is encrypted at rest if PPE_FERNET_KEY set; else plain (dev)
    password = models.CharField(max_length=500, blank=True, help_text="Password (encrypted at rest if PPE_FERNET_KEY set)")

    location = models.CharField(max_length=200, blank=True, help_text="Physical location / zone description")
    description = models.TextField(blank=True)

    # Operational
    is_active = models.BooleanField(default=True, db_index=True, help_text="Enable/disable this camera")
    detection_enabled = models.BooleanField(default=True, help_text="Run PPE detection on this stream")
    confidence_threshold = models.FloatField(
        default=0.6,
        validators=[MinValueValidator(0.1), MaxValueValidator(1.0)],
        help_text="YOLO confidence for this camera",
    )
    # Health
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="unknown", db_index=True)
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.CharField(max_length=500, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0, help_text="For circuit-breaker / alert throttling")
    uptime_24h = models.FloatField(default=0.0, help_text="Uptime % last 24h (0-100)")

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="cameras_created")
    updated_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="cameras_updated")

    class Meta:
        ordering = ["-is_active", "zone__name", "name"]
        verbose_name = "IP Camera"
        verbose_name_plural = "IP Cameras"
        unique_together = [("ip_address", "port", "stream_path")]
        indexes = [
            models.Index(fields=["is_active", "status"]),
            models.Index(fields=["zone", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(check=models.Q(port__gte=1) & models.Q(port__lte=65535), name="port_range"),
            models.CheckConstraint(check=models.Q(confidence_threshold__gte=0.1) & models.Q(confidence_threshold__lte=1.0), name="conf_range"),
        ]

    def __str__(self):
        return f"{self.name} ({self.ip_address}:{self.port})"

    def clean(self):
        super().clean()
        # Validate stream_path
        if not self.stream_path.startswith("/"):
            raise ValidationError({"stream_path": "Must start with /"})
        # If hostname was allowed via form, GenericIPAddressField would have already validated; we support hostname bypass via form's clean_ip_address
        # Validate IP/hostname length
        if len(self.ip_address) > 255:
            raise ValidationError({"ip_address": "Too long"})

    def save(self, *args, **kwargs):
        # Encrypt password at rest if needed and not already encrypted
        if self.password and not self.password.startswith("enc$"):
            # Detect if Fernet is configured; if so, encrypt
            if _get_fernet():
                self.password = encrypt_value(self.password)
        # Normalize stream_path
        if self.stream_path and not self.stream_path.startswith("/"):
            self.stream_path = "/" + self.stream_path
        super().save(*args, **kwargs)

    def get_plain_password(self) -> str:
        return decrypt_value(self.password)

    @property
    def stream_url(self) -> str:
        """Build full stream URL including auth if provided (uses plain password)"""
        plain = self.get_plain_password()
        auth = f"{self.username}:{plain}@" if self.username else ""
        # For templating/logging, never log plain password
        if self.protocol in ("http", "https"):
            return f"{self.protocol}://{auth}{self.ip_address}:{self.port}{self.stream_path}"
        else:  # rtsp / rtsp_tcp
            return f"rtsp://{auth}{self.ip_address}:{self.port}{self.stream_path}"

    @property
    def display_url(self) -> str:
        """Masked URL for UI (hide password)"""
        auth = f"{self.username}:****@" if self.get_plain_password() else (f"{self.username}@" if self.username else "")
        proto = "rtsp" if self.protocol == "rtsp_tcp" else self.protocol
        return f"{proto}://{auth}{self.ip_address}:{self.port}{self.stream_path}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("monitor:camera_edit", args=[self.pk])

    def test_connection(self, timeout: int = 5) -> tuple[bool, str]:
        """Try to open stream with cv2.VideoCapture for a single frame. Updates last_seen/error but does not save by default in this method? Caller saves."""
        try:
            import cv2
        except ImportError:
            return False, "OpenCV not installed"
        try:
            if self.protocol == "rtsp_tcp":
                import os
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
            cap = cv2.VideoCapture(self.stream_url)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout * 1000)
            if not cap.isOpened():
                return False, "Cannot open stream (check IP/port/path/auth/firewall)"
            ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                return False, "Opened but no frame received (codec/auth)"
            return True, f"OK - {frame.shape[1]}x{frame.shape[0]} @ {frame.shape[2]}ch"
        except Exception as e:
            logger.exception(f"test_connection {self.name} failed")
            return False, str(e)[:500]

    def record_health(self, ok: bool, message: str = ""):
        """Update health counters and create CameraHealthLog entry. Industry: uptime + circuit breaker."""
        from django.utils import timezone as tz
        if ok:
            self.status = "active" if self.is_active else "inactive"
            self.last_seen = tz.now()
            self.last_error = ""
            self.consecutive_failures = 0
        else:
            self.consecutive_failures = (self.consecutive_failures or 0) + 1
            # After 3 consecutive failures, mark error; else keep last status
            if self.consecutive_failures >= 3:
                self.status = "error"
            self.last_error = message[:500]
        self.save(update_fields=["status", "last_seen", "last_error", "consecutive_failures", "updated_at"])
        # Log
        try:
            CameraHealthLog.objects.create(camera=self, is_ok=ok, message=message[:500], latency_ms=None)
            # Update uptime_24h as % of ok logs in last 24h (lightweight)
            from django.utils import timezone
            from datetime import timedelta
            since = timezone.now() - timedelta(hours=24)
            recent = CameraHealthLog.objects.filter(camera=self, checked_at__gte=since)
            total = recent.count()
            if total > 0:
                ok_cnt = recent.filter(is_ok=True).count()
                self.uptime_24h = round(ok_cnt / total * 100, 1)
                self.save(update_fields=["uptime_24h"])
        except Exception as e:
            logger.warning(f"health log failed: {e}")

class CameraHealthLog(models.Model):
    """Immutable log of health checks for SLA / uptime reporting (industry: retain 30 days)"""
    camera = models.ForeignKey(IPCamera, on_delete=models.CASCADE, related_name="health_logs")
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_ok = models.BooleanField(db_index=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    message = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [models.Index(fields=["camera", "-checked_at"])]
        verbose_name = "Camera Health Log"
        verbose_name_plural = "Camera Health Logs"

    def __str__(self):
        return f"{self.camera.name} {'OK' if self.is_ok else 'FAIL'} @ {self.checked_at:%H:%M:%S}"

class Violation(models.Model):
    VIOLATION_CHOICES = [
        ("DETECTED", "Detected"),
        ("RESOLVED", "Resolved"),
    ]

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    person_id = models.CharField(max_length=64, db_index=True)
    missing_items = models.JSONField(default=list, help_text="List of missing PPE items")
    violation_type = models.CharField(max_length=10, choices=VIOLATION_CHOICES, default="DETECTED", db_index=True)
    duration = models.FloatField(null=True, blank=True, help_text="Duration in seconds if resolved")
    resolution_time = models.DateTimeField(null=True, blank=True)
    image = models.ImageField(upload_to="violations/%Y/%m/%d/", null=True, blank=True)
    camera = models.ForeignKey(IPCamera, null=True, blank=True, on_delete=models.SET_NULL, related_name="violations", help_text="Camera that captured this violation")
    zone = models.ForeignKey(CameraZone, null=True, blank=True, on_delete=models.SET_NULL, related_name="violations", help_text="Denormalized zone at violation time")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "PPE Violation"
        verbose_name_plural = "PPE Violations"
        indexes = [
            models.Index(fields=["camera", "-timestamp"]),
            models.Index(fields=["zone", "-timestamp"]),
            models.Index(fields=["violation_type", "-timestamp"]),
        ]

    def __str__(self):
        cam = f" {self.camera.name}" if self.camera else ""
        return f"Violation {self.person_id}{cam} @ {self.timestamp:%Y-%m-%d %H:%M:%S} - {self.violation_type}"

    @property
    def missing_items_display(self):
        if isinstance(self.missing_items, list):
            return ", ".join(self.missing_items)
        try:
            items = json.loads(self.missing_items)  # type: ignore
            return ", ".join(items)
        except Exception:
            return str(self.missing_items)

class DetectionSession(models.Model):
    """Track an upload / live session for analytics"""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    session_type = models.CharField(max_length=20, choices=[("image", "Image"), ("video", "Video"), ("live", "Live")], default="image", db_index=True)
    file = models.FileField(upload_to="sessions/%Y/%m/%d/", null=True, blank=True)
    camera = models.ForeignKey(IPCamera, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions")
    person_count = models.IntegerField(default=0)
    violation_count = models.IntegerField(default=0)
    compliant_count = models.IntegerField(default=0)
    processing_time_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        cam = f" {self.camera.name}" if self.camera else ""
        return f"{self.session_type}{cam} session {self.id} - {self.created_at:%H:%M:%S}"

class AuditLog(models.Model):
    """Industry: immutable audit trail for camera/config changes (who, what, when)"""
    ACTION_CHOICES = [("create", "Create"), ("update", "Update"), ("delete", "Delete"), ("test", "Test"), ("toggle", "Toggle")]

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    entity = models.CharField(max_length=50, help_text="e.g., IPCamera")
    entity_id = models.CharField(max_length=50)
    detail = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.user} {self.action} {self.entity}#{self.entity_id}"
