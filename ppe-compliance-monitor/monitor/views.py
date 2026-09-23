"""
Django views for PPE Compliance Monitoring
Replaces Streamlit app.py with Django class/function views + JSON APIs
"""
import base64
import json
import logging
import time
from pathlib import Path
from datetime import datetime

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    np = None
    HAS_NP = False

from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.files.storage import default_storage
from django.utils import timezone

from .utils.config import PPEConfig
from .utils.detector import get_detector
from .utils.violation_tracker import get_tracker
from .forms import ImageUploadForm, VideoUploadForm

logger = logging.getLogger(__name__)

# ---------- Helpers ----------

def _decode_base64_image(data_url: str):
    """Decode data:image/jpeg;base64,xxx to cv2 BGR array"""
    if not HAS_CV2 or not HAS_NP:
        logger.warning("cv2/numpy not available - image decode mocked")
        return None
    try:
        if ',' in data_url:
            header, data = data_url.split(',', 1)
        else:
            data = data_url
        nparr = np.frombuffer(base64.b64decode(data), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        logger.error(f"Base64 decode failed: {e}")
        return None

def _encode_image_to_base64(img, fmt='.jpg', quality=85):
    """Encode BGR image to data URL base64"""
    if not HAS_CV2:
        return None
    try:
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        success, buf = cv2.imencode(fmt, img, encode_param)
        if not success:
            return None
        b64 = base64.b64encode(buf).decode('utf-8')
        mime = 'image/jpeg' if fmt == '.jpg' else 'image/png'
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.error(f"Encode failed: {e}")
        return None

def _process_frame_array(frame, confidence=None, iou=None):
    """Run detection pipeline on a single BGR frame"""
    start = time.time()
    cfg = PPEConfig()
    if confidence is not None:
        try: cfg.CONFIDENCE_THRESHOLD = float(confidence)
        except: pass
    if iou is not None:
        try: cfg.IOU_THRESHOLD = float(iou)
        except: pass

    # If config differs from singleton, create fresh detector; else reuse
    # For speed, only override if needed
    if confidence is not None or iou is not None:
        from .utils.detector import PPEDetector
        detector = PPEDetector(cfg)
    else:
        detector = get_detector()

    detections = detector.detect(frame)
    compliance = detector.analyze_compliance(detections)
    annotated = detector.annotate_frame(frame, detections, compliance)

    # Update violation tracker
    tracker = get_tracker()
    tracker.update(compliance, datetime.now())

    elapsed_ms = int((time.time() - start) * 1000)
    return annotated, compliance, detections, elapsed_ms

# ---------- Page Views ----------

def _model_status():
    try:
        from pathlib import Path
        from django.conf import settings as s
        if (Path(s.PPE_ML_MODELS_DIR) / "ppe_yolov10n.pt").exists():
            return True
        det = get_detector()
        return det.model is not None
    except:
        return False

def index(request):
    """Home / Overview dashboard - equivalent to Streamlit main page"""
    tracker = get_tracker()
    stats = tracker.get_violation_stats(hours=24)
    form = ImageUploadForm()
    context = {
        'stats': stats,
        'form': form,
        'model_loaded': _model_status(),
        'active_page': 'home',
        'stats_json': json.dumps(stats, default=str),
    }
    return render(request, 'monitor/index.html', context)

def live_monitor(request):
    """Live monitoring page with webcam"""
    tracker = get_tracker()
    stats = tracker.get_violation_stats(hours=24)
    context = {
        'stats': stats,
        'model_loaded': _model_status(),
        'active_page': 'live',
    }
    return render(request, 'monitor/live.html', context)

def dashboard(request):
    """Analytics dashboard (detailed charts)"""
    hours = int(request.GET.get('hours', 24))
    tracker = get_tracker()
    stats = tracker.get_violation_stats(hours=hours)
    recent_df = tracker.get_recent_violations_df(limit=100)
    context = {
        'stats': stats,
        'hours': hours,
        'recent_df': recent_df,
        'model_loaded': _model_status(),
        'active_page': 'dashboard',
        'stats_json': json.dumps(stats, default=str),
    }
    return render(request, 'monitor/dashboard.html', context)

def violations_log(request):
    """Violations log table view"""
    tracker = get_tracker()
    limit = int(request.GET.get('limit', 50))
    df = tracker.get_recent_violations_df(limit=limit)
    violations_orm = []
    try:
        from .models import Violation
        violations_orm = Violation.objects.all()[:50]
    except: pass
    context = {
        'df': df,
        'violations_orm': violations_orm,
        'model_loaded': _model_status(),
        'active_page': 'violations',
        'limit': limit,
    }
    return render(request, 'monitor/violations.html', context)

def upload_view(request):
    """Image/Video upload processing page"""
    image_form = ImageUploadForm()
    video_form = VideoUploadForm()
    result = None
    annotated_b64 = None
    compliance = None
    model_loaded = _model_status()

    if request.method == 'POST':
        if 'image' in request.FILES:
            image_form = ImageUploadForm(request.POST, request.FILES)
            if image_form.is_valid():
                f = request.FILES['image']
                # Save to media for record
                path = default_storage.save(f"uploads/{timezone.now():%Y/%m/%d}/{f.name}", f)
                full_path = Path(settings.MEDIA_ROOT) / path
                # Read with cv2
                file_bytes = full_path.read_bytes()
                nparr = np.frombuffer(file_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is not None:
                    conf = request.POST.get('confidence') or 0.6
                    annotated, compliance, _, elapsed = _process_frame_array(frame, confidence=conf)
                    annotated_b64 = _encode_image_to_base64(annotated)
                    result = {'type':'image','path': path, 'elapsed': elapsed}
                else:
                    result = {'error': 'Could not decode image'}
        elif 'video' in request.FILES:
            video_form = VideoUploadForm(request.POST, request.FILES)
            if video_form.is_valid():
                f = request.FILES['video']
                path = default_storage.save(f"uploads/{timezone.now():%Y/%m/%d}/{f.name}", f)
                result = {'type':'video','path': path, 'message': 'Video uploaded. Use video processing API to annotate.'}
                # For quick demo, we process first frame only
                full_path = Path(settings.MEDIA_ROOT) / path
                cap = cv2.VideoCapture(str(full_path))
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None:
                    annotated, compliance, _, elapsed = _process_frame_array(frame)
                    annotated_b64 = _encode_image_to_base64(annotated)
                    result['preview_first_frame'] = True

    context = {
        'image_form': image_form,
        'video_form': video_form,
        'result': result,
        'annotated_b64': annotated_b64,
        'compliance': compliance,
        'model_loaded': model_loaded,
        'active_page': 'upload',
    }
    return render(request, 'monitor/upload.html', context)

# ---------- API Views ----------

@csrf_exempt
@require_http_methods(["POST"])
def api_process_frame(request):
    """
    Process a single base64 frame from browser webcam.
    POST JSON: {image: "data:image/jpeg;base64,...", confidence: 0.6, iou: 0.5}
    Returns: {annotated_image, compliance, stats}
    """
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST

        b64_image = data.get('image') or data.get('frame')
        if not b64_image:
            return JsonResponse({'error': 'No image provided'}, status=400)

        confidence = data.get('confidence')
        iou = data.get('iou')

        frame = _decode_base64_image(b64_image)
        if frame is None:
            return JsonResponse({'error': 'Invalid image data'}, status=400)

        annotated, compliance, _, elapsed_ms = _process_frame_array(frame, confidence, iou)
        annotated_b64 = _encode_image_to_base64(annotated)

        tracker = get_tracker()
        stats = tracker.get_violation_stats(hours=24)

        return JsonResponse({
            'annotated_image': annotated_b64,
            'compliance': compliance,
            'stats': {
                'person_count': compliance.get('person_count', 0),
                'violations': len(compliance.get('violations', [])),
                'compliant': len(compliance.get('compliant', [])),
                'active_violations': stats.get('active_violations', 0),
            },
            'full_stats': stats,
            'processing_time_ms': elapsed_ms,
        })
    except Exception as e:
        logger.exception("api_process_frame error")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def api_detect_image(request):
    """
    Multipart image upload detection.
    POST form-data: image file
    Returns JSON with annotated image base64 + compliance
    """
    try:
        if 'image' not in request.FILES and 'file' not in request.FILES:
            return JsonResponse({'error': 'No image file uploaded (field name: image)'}, status=400)

        f = request.FILES.get('image') or request.FILES.get('file')
        confidence = request.POST.get('confidence') or request.GET.get('confidence')
        iou = request.POST.get('iou') or request.GET.get('iou')

        # Save temporarily
        raw = f.read()
        nparr = np.frombuffer(raw, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return JsonResponse({'error': 'Could not decode image - unsupported format'}, status=400)

        annotated, compliance, _, elapsed_ms = _process_frame_array(frame, confidence, iou)
        annotated_b64 = _encode_image_to_base64(annotated)

        # Optionally save annotated to media
        save_path = None
        try:
            # Save annotated for download
            fname = f"annotated_{int(time.time())}.jpg"
            rel = f"results/{fname}"
            full = Path(settings.MEDIA_ROOT) / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(full), annotated)
            save_path = settings.MEDIA_URL + rel
        except Exception as e:
            logger.warning(f"Save annotated failed: {e}")

        return JsonResponse({
            'annotated_image': annotated_b64,
            'annotated_url': save_path,
            'compliance': compliance,
            'processing_time_ms': elapsed_ms,
        })
    except Exception as e:
        logger.exception("api_detect_image error")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def api_stats(request):
    """Return violation stats JSON"""
    try:
        hours = int(request.GET.get('hours', 24))
    except:
        hours = 24
    tracker = get_tracker()
    stats = tracker.get_violation_stats(hours=hours)
    return JsonResponse(stats)

@csrf_exempt
@require_http_methods(["GET"])
def api_violations(request):
    """Return recent violations JSON"""
    limit = int(request.GET.get('limit', 20))
    tracker = get_tracker()
    df = tracker.get_recent_violations_df(limit=limit)
    # Convert to list
    violations = []
    if not df.empty:
        for _, row in df.iterrows():
            try:
                import json as js
                items = js.loads(row['missing_items']) if isinstance(row['missing_items'], str) else row['missing_items']
            except:
                items = []
            violations.append({
                'timestamp': str(row['timestamp']),
                'person_id': str(row['person_id']),
                'missing_items': items,
                'violation_type': str(row['violation_type']),
                'duration': float(row['duration']) if str(row['duration']) != 'nan' and row['duration'] is not None else None,
                'resolution_time': str(row.get('resolution_time', '')),
            })
    return JsonResponse({'violations': violations, 'count': len(violations)})

def api_health(request):
    """Health check"""
    has_model = False
    try:
        from django.conf import settings
        has_model = (Path(settings.PPE_ML_MODELS_DIR) / "ppe_yolov10n.pt").exists()
        # Also check ultralytics cache for yolov10n.pt
        if not has_model:
            # Check if detector loaded
            det = get_detector()
            has_model = det.model is not None
    except: pass
    return JsonResponse({
        'status': 'ok',
        'model_loaded': has_model,
        'timestamp': timezone.now().isoformat(),
    })

# Optional MJPEG streaming from server camera (if available)
def video_feed(request):
    """MJPEG streaming - tries to open server camera 0; falls back to placeholder"""
    def gen():
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            # Return single frame placeholder as stream
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "No camera available", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255,255,255), 2)
            cv2.putText(placeholder, "Use browser webcam on Live page", (110, 270), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)
            ret, buf = cv2.imencode('.jpg', placeholder)
            frame = buf.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            return

        detector = get_detector()
        tracker = get_tracker()
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.1)
                    continue
                detections = detector.detect(frame)
                compliance = detector.analyze_compliance(detections)
                tracker.update(compliance, datetime.now())
                annotated = detector.annotate_frame(frame, detections, compliance)
                ret2, buf = cv2.imencode('.jpg', annotated)
                if not ret2:
                    continue
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                time.sleep(0.05)
        finally:
            cap.release()

    return StreamingHttpResponse(gen(), content_type='multipart/x-mixed-replace; boundary=frame')

def export_violations_csv(request):
    """Download violations CSV"""
    tracker = get_tracker()
    path = tracker.violation_log_path
    if path.exists():
        with open(path, 'rb') as f:
            resp = HttpResponse(f.read(), content_type='text/csv')
            resp['Content-Disposition'] = 'attachment; filename="violations.csv"'
            return resp
    return HttpResponse("No violations logged yet.", content_type="text/plain", status=404)
