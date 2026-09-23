from django import forms

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
