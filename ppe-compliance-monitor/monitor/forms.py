from django import forms
from .models import IPCamera, CameraZone
import ipaddress
import re

class ImageUploadForm(forms.Form):
    image = forms.ImageField(
        label="Upload Image",
        help_text="JPG, PNG, WebP up to 10MB",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*", "class": "form-control"}),
    )
    confidence = forms.FloatField(
        initial=0.6, min_value=0.1, max_value=1.0, step_size=0.05,
        widget=forms.NumberInput(attrs={"class": "form-range", "type": "range", "min": "0.1", "max": "1.0", "step": "0.05"}),
        required=False,
    )

class VideoUploadForm(forms.Form):
    video = forms.FileField(
        label="Upload Video",
        help_text="MP4, AVI, MOV up to 50MB",
        widget=forms.ClearableFileInput(attrs={"accept": "video/*", "class": "form-control"}),
    )
    confidence = forms.FloatField(initial=0.6, min_value=0.1, max_value=1.0, step_size=0.05, required=False)

class IPCameraForm(forms.ModelForm):
    class Meta:
        model = IPCamera
        fields = ["name","zone","ip_address","port","protocol","stream_path","username","password","location","description","is_active","detection_enabled","confidence_threshold"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Gate-01, Workshop-North", "required": "required"}),
            "zone": forms.Select(attrs={"class": "form-select"}),
            "ip_address": forms.TextInput(attrs={"class": "form-control", "placeholder": "192.168.1.64 or camera.local", "required": "required"}),
            "port": forms.NumberInput(attrs={"class": "form-control", "min": "1", "max": "65535"}),
            "protocol": forms.Select(attrs={"class": "form-select"}),
            "stream_path": forms.TextInput(attrs={"class": "form-control", "placeholder": "/stream1 or /live/ch1 or /video.mjpg"}),
            "username": forms.TextInput(attrs={"class": "form-control", "placeholder": "optional", "autocomplete": "off"}),
            "password": forms.PasswordInput(attrs={"class": "form-control", "placeholder": "optional (encrypted at rest if PPE_FERNET_KEY set)"}, render_value=True),
            "location": forms.TextInput(attrs={"class": "form-control", "placeholder": "Building A, Floor 2"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Optional notes, e.g., Hikvision DS-2CD2043G2-I, ONVIF port 80"}),
            "confidence_threshold": forms.NumberInput(attrs={"class": "form-control", "step": "0.05", "min": "0.1", "max": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Zone choices with empty
        self.fields["zone"].required = False
        self.fields["zone"].empty_label = "— No zone —"
        # If editing and password is encrypted, show placeholder not actual
        if self.instance and self.instance.pk and self.instance.password:
            # Don't expose encrypted value; if user leaves blank, keep existing
            self.fields["password"].required = False
            self.fields["password"].help_text = "Leave blank to keep existing, or enter new to update (encrypted at rest)"

    def clean_ip_address(self):
        ip = self.cleaned_data["ip_address"].strip()
        # Allow hostname (letters, numbers, hyphens, dots) or IP
        try:
            ipaddress.ip_address(ip)
            return ip
        except ValueError:
            # Hostname validation (RFC 1123)
            if len(ip) > 253:
                raise forms.ValidationError("Hostname too long")
            if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$", ip):
                raise forms.ValidationError("Enter a valid IPv4/IPv6 address or hostname (e.g., 192.168.1.64 or camera.local)")
            if ".." in ip or ".-" in ip or "-." in ip:
                raise forms.ValidationError("Invalid hostname")
            if "." not in ip and ip != "localhost":
                raise forms.ValidationError("Enter a valid IPv4/IPv6 address or hostname")
            return ip.lower()

    def clean_stream_path(self):
        p = self.cleaned_data.get("stream_path", "").strip()
        if not p:
            return "/stream1"
        if not p.startswith("/"):
            p = "/" + p
        # Basic path traversal guard
        if ".." in p or "//" in p:
            raise forms.ValidationError("Invalid path")
        return p

    def clean_port(self):
        port = self.cleaned_data.get("port")
        if port and (port < 1 or port > 65535):
            raise forms.ValidationError("Port must be 1-65535")
        return port

    def clean(self):
        cleaned = super().clean()
        # If password left blank on edit, keep existing
        if self.instance and self.instance.pk:
            if not cleaned.get("password"):
                cleaned["password"] = self.instance.password
            # else new password will be encrypted in model save()
        return cleaned

class BulkIPForm(forms.Form):
    ips = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control font-monospace", "rows": 6, "placeholder": "192.168.1.10:554/stream1\n192.168.1.11:554/stream1\n10.0.0.5:8080/video.mjpg\nrtsp://admin:pass@192.168.1.10:554/live/ch1\nOr just IPs, one per line - port/path will default to 554/stream1", "spellcheck": "false"}),
        label="IP Addresses (one per line)",
        help_text="Formats: 192.168.1.10  |  192.168.1.10:554  |  192.168.1.10:554/stream1  |  rtsp://user:pass@192.168.1.10:554/live/ch1  |  Supports hostname too",
    )
    protocol = forms.ChoiceField(choices=IPCamera.PROTOCOL_CHOICES, initial="rtsp", widget=forms.Select(attrs={"class": "form-select"}))
    zone = forms.ModelChoiceField(queryset=CameraZone.objects.all(), required=False, empty_label="— No zone —", widget=forms.Select(attrs={"class": "form-select"}))
    location = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional zone/location for all (overrides zone name)"}))
    confidence_threshold = forms.FloatField(initial=0.6, min_value=0.1, max_value=1.0, required=False, widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.05"}))

    def clean_ips(self):
        raw = self.cleaned_data["ips"]
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if not lines:
            raise forms.ValidationError("Enter at least one IP/host")
        if len(lines) > 100:
            raise forms.ValidationError("Max 100 IPs per bulk add (industry: batch to avoid overwhelming NVR)")
        return raw

class CameraZoneForm(forms.ModelForm):
    class Meta:
        model = CameraZone
        fields = ["name","description","is_critical"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Workshop A, Gate-1"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }
