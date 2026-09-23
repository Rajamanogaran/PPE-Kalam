from django.apps import AppConfig


class MonitorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'monitor'
    verbose_name = 'PPE Compliance Monitor'

    def ready(self):
        # Ensure directories exist on startup
        from pathlib import Path
        from django.conf import settings
        Path(settings.PPE_ML_MODELS_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.PPE_LOGS_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
