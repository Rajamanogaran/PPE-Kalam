"""
Django management command to download PPE models.
Replaces original models/download_models.py
Usage: python manage.py download_models
"""
from django.core.management.base import BaseCommand
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Download or initialize PPE YOLOv10 model (fallback to pretrained yolov10n)'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Force re-download even if exists')

    def handle(self, *args, **options):
        from django.conf import settings
        model_dir = Path(settings.PPE_ML_MODELS_DIR)
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / "ppe_yolov10n.pt"
        fallback_name = "yolov10n.pt"

        if model_path.exists() and not options['force']:
            self.stdout.write(self.style.SUCCESS(f"✅ Model already exists at {model_path}"))
            return

        self.stdout.write("🔄 Initializing PPE model...")

        try:
            from ultralytics import YOLO
            # This will download yolov10n.pt if not cached
            self.stdout.write(f"📥 Downloading / loading {fallback_name} (may take a minute on first run)...")
            model = YOLO(fallback_name)
            # Save a copy as ppe_yolov10n.pt for consistency
            try:
                model.save(str(model_path))
                self.stdout.write(self.style.SUCCESS(f"✅ Model saved to {model_path}"))
            except Exception as e:
                # Newer ultralytics may not have .save; just ensure fallback is cached
                self.stdout.write(self.style.WARNING(f"⚠️ Could not save copy: {e}. Fallback model is cached as {fallback_name}"))
                self.stdout.write(self.style.SUCCESS("✅ Pretrained model ready (cached by ultralytics)"))
        except ImportError:
            self.stdout.write(self.style.ERROR("❌ ultralytics not installed. Run pip install -r requirements.txt"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to download model: {e}"))
            self.stdout.write("ℹ️ The app will still run in mock/detection-disabled mode, but install will be needed for real inference.")
            logger.exception(e)
