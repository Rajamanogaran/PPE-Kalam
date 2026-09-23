from django import forms
from .models import IPCamera
import ipaddress

class ImageUploadForm(forms.Form):
    image = forms.ImageField(
        label='Upload Image',
        help_text='JPG, PNG, WebP up to 10MB',
        widget=forms.ClearableFileInput(attrs={'accept':'image/*', 'class':'form-control'})
    )
    confidence = forms.FloatField(
        initial=0.6, min_value=0.1, max_value=1.0, step_size=0.05,
        widget=forms.NumberInput(attrs={'class':'form-range', 'type':'range', 'min':'0.1','max':'1.0','step':'0.05'}),
        required=False
    )

class VideoUploadForm(forms.Form):
    video = forms.FileField(
        label='Upload Video',
        help_text='MP4, AVI, MOV up to 50MB',
        widget=forms.ClearableFileInput(attrs={'accept':'video/*', 'class':'form-control'})
    )
    confidence = forms.FloatField(
        initial=0.6, min_value=0.1, max_value=1.0, step_size=0.05,
        required=False
    )

class IPCameraForm(forms.ModelForm):
    class Meta:
        model = IPCamera
        fields = ['name','ip_address','port','protocol','stream_path','username','password','location','description','is_active','detection_enabled','confidence_threshold']
        widgets = {
            'name': forms.TextInput(attrs={'class':'form-control','placeholder':'e.g., Gate-01, Workshop-North'}),
            'ip_address': forms.TextInput(attrs={'class':'form-control','placeholder':'192.168.1.64'}),
            'port': forms.NumberInput(attrs={'class':'form-control'}),
            'protocol': forms.Select(attrs={'class':'form-select'}),
            'stream_path': forms.TextInput(attrs={'class':'form-control','placeholder':'/stream1 or /live/ch1 or /video.mjpg'}),
            'username': forms.TextInput(attrs={'class':'form-control','placeholder':'optional'}),
            'password': forms.PasswordInput(attrs={'class':'form-control','placeholder':'optional'}, render_value=True),
            'location': forms.TextInput(attrs={'class':'form-control','placeholder':'Building A, Floor 2'}),
            'description': forms.Textarea(attrs={'class':'form-control','rows':2}),
            'confidence_threshold': forms.NumberInput(attrs={'class':'form-control','step':'0.05','min':'0.1','max':'1'}),
        }

    def clean_ip_address(self):
        ip = self.cleaned_data['ip_address']
        # Allow hostname as well? GenericIPAddressField already validates, but we also support hostname fallback
        # If it fails ip check, try as hostname
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            # If not IP, check if looks like hostname
            if '.' not in ip and ip != 'localhost':
                raise forms.ValidationError("Enter a valid IPv4/IPv6 address or hostname")
        return ip

class BulkIPForm(forms.Form):
    ips = forms.CharField(
        widget=forms.Textarea(attrs={'class':'form-control','rows':6,'placeholder':'192.168.1.10:554/stream1\n192.168.1.11:554/stream1\n10.0.0.5:8080/video.mjpg\nOr just IPs, one per line - port/path will default to 554/stream1'}),
        label="IP Addresses (one per line)",
        help_text="Formats: 192.168.1.10  |  192.168.1.10:554  |  192.168.1.10:554/stream1  |  rtsp://user:pass@192.168.1.10:554/live/ch1"
    )
    protocol = forms.ChoiceField(choices=IPCamera.PROTOCOL_CHOICES, initial='rtsp', widget=forms.Select(attrs={'class':'form-select'}))
    location = forms.CharField(required=False, widget=forms.TextInput(attrs={'class':'form-control','placeholder':'Optional zone for all'}))
    confidence_threshold = forms.FloatField(initial=0.6, min_value=0.1, max_value=1.0, required=False, widget=forms.NumberInput(attrs={'class':'form-control','step':'0.05'}))

