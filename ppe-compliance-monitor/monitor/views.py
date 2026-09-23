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
from .forms import ImageUploadForm, VideoUploadForm, IPCameraForm, BulkIPForm
from .models import IPCamera

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

# ---------- IP Camera Management ----------
import re

def ip_camera_list(request):
    """List all configured IP cameras with status and quick actions"""
    cameras = IPCamera.objects.all().order_by('-is_active', 'name')
    stats = {
        'total': cameras.count(),
        'active': cameras.filter(is_active=True).count(),
        'detection_on': cameras.filter(detection_enabled=True, is_active=True).count(),
        'error': cameras.filter(status='error').count(),
    }
    # Also get violation counts per camera if ORM has data
    form = IPCameraForm()
    bulk_form = BulkIPForm()
    context = {
        'cameras': cameras,
        'stats': stats,
        'form': form,
        'bulk_form': bulk_form,
        'model_loaded': _model_status(),
        'active_page': 'cameras',
    }
    return render(request, 'monitor/cameras.html', context)

def ip_camera_create(request):
    if request.method == 'POST':
        form = IPCameraForm(request.POST)
        if form.is_valid():
            cam = form.save()
            # Try to test connection async? just save and redirect
            from django.contrib import messages
            messages.success(request, f"Camera '{cam.name}' added ({cam.ip_address}:{cam.port})")
            return JsonResponse({'ok': True, 'id': cam.id, 'name': cam.name}) if request.headers.get('x-requested-with') == 'XMLHttpRequest' else render(request, 'monitor/camera_form.html', {'form': IPCameraForm(), 'created': cam})
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
    else:
        form = IPCameraForm()
    # For non-AJAX, render inline? We'll handle via cameras page modal; direct GET shows form
    if request.method == 'GET' and not request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'monitor/camera_form.html', {'form': form, 'active_page': 'cameras', 'model_loaded': _model_status()})
    return JsonResponse({'ok': False, 'errors': form.errors if 'form' in locals() else {}}, status=400)

def ip_camera_edit(request, pk):
    try:
        cam = IPCamera.objects.get(pk=pk)
    except IPCamera.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
    if request.method == 'POST':
        form = IPCameraForm(request.POST, instance=cam)
        if form.is_valid():
            cam = form.save()
            return JsonResponse({'ok': True, 'id': cam.id})
        else:
            return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
    else:
        form = IPCameraForm(instance=cam)
        return render(request, 'monitor/camera_form.html', {'form': form, 'camera': cam, 'active_page': 'cameras', 'model_loaded': _model_status()})

@csrf_exempt
def ip_camera_delete(request, pk):
    if request.method not in ('POST','DELETE'):
        return JsonResponse({'error': 'Use POST/DELETE'}, status=405)
    try:
        cam = IPCamera.objects.get(pk=pk)
        name = cam.name
        cam.delete()
        return JsonResponse({'ok': True, 'name': name})
    except IPCamera.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

@csrf_exempt
def ip_camera_toggle(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        cam = IPCamera.objects.get(pk=pk)
        field = request.POST.get('field', 'is_active')
        if field not in ('is_active','detection_enabled'):
            field = 'is_active'
        setattr(cam, field, not getattr(cam, field))
        cam.save(update_fields=[field, 'updated_at'])
        return JsonResponse({'ok': True, 'field': field, 'value': getattr(cam, field)})
    except IPCamera.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

def ip_camera_test(request, pk):
    try:
        cam = IPCamera.objects.get(pk=pk)
    except IPCamera.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
    ok, msg = cam.test_connection()
    # Update status
    cam.status = 'active' if ok else 'error'
    cam.last_error = '' if ok else msg[:500]
    if ok:
        from django.utils import timezone as tz
        cam.last_seen = tz.now()
    cam.save(update_fields=['status','last_error','last_seen','updated_at'])
    return JsonResponse({'ok': ok, 'message': msg, 'status': cam.status, 'url': cam.display_url})

def ip_camera_snapshot(request, pk):
    """Return a single JPEG snapshot from the IP camera with optional PPE overlay"""
    try:
        cam = IPCamera.objects.get(pk=pk)
    except IPCamera.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
    if not HAS_CV2:
        return JsonResponse({'error': 'OpenCV not available'}, status=500)
    detect = request.GET.get('detect', '1') == '1'
    # Try to capture
    try:
        cap = cv2.VideoCapture(cam.stream_url)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
        if not cap.isOpened():
            return JsonResponse({'error': f'Cannot open {cam.display_url}'}, status=502)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return JsonResponse({'error': 'No frame received'}, status=502)
        # Update last_seen
        try:
            cam.last_seen = timezone.now()
            cam.status = 'active'
            cam.last_error = ''
            cam.save(update_fields=['last_seen','status','last_error'])
        except: pass

        if detect and cam.detection_enabled:
            try:
                cfg = PPEConfig()
                cfg.CONFIDENCE_THRESHOLD = cam.confidence_threshold
                from .utils.detector import PPEDetector
                detector = PPEDetector(cfg)
                detections = detector.detect(frame)
                compliance = detector.analyze_compliance(detections)
                # Add camera id to violation log? Track
                frame = detector.annotate_frame(frame, detections, compliance)
                # Optionally log violations with camera link
                # we pass compliance through header? For snapshot we don't log to CSV to avoid spam, but could
            except Exception as e:
                logger.warning(f"Snapshot detect failed: {e}")
        # Encode jpeg
        ret2, buf = cv2.imencode('.jpg', frame)
        if not ret2:
            return JsonResponse({'error': 'Encode failed'}, status=500)
        return HttpResponse(buf.tobytes(), content_type='image/jpeg')
    except Exception as e:
        logger.exception("snapshot error")
        return JsonResponse({'error': str(e)}, status=500)

def ip_camera_stream(request, pk):
    """MJPEG stream from IP camera with live PPE detection overlay"""
    try:
        cam = IPCamera.objects.get(pk=pk)
    except IPCamera.DoesNotExist:
        return HttpResponse("Camera not found", status=404)
    if not HAS_CV2:
        return HttpResponse("OpenCV not installed", status=500)

    def gen():
        # Try to open
        import os
        if cam.protocol == 'rtsp_tcp':
            os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'
        cap = cv2.VideoCapture(cam.stream_url)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 7000)
        if not cap.isOpened():
            # Send error frame
            err = np.zeros((480,640,3), dtype=np.uint8)
            cv2.putText(err, f"Cannot open {cam.display_url}", (20,240), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255),2)
            cv2.putText(err, f"Check IP/port/path", (20,270), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255),1)
            ret, buf = cv2.imencode('.jpg', err)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
            return
        # Setup detector per camera
        cfg = PPEConfig()
        cfg.CONFIDENCE_THRESHOLD = cam.confidence_threshold
        try:
            from .utils.detector import PPEDetector
            detector = PPEDetector(cfg)
        except:
            detector = get_detector()
        tracker = get_tracker()
        try:
            while True:
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(0.1)
                    continue
                # Run detection if enabled
                if cam.detection_enabled:
                    try:
                        detections = detector.detect(frame)
                        compliance = detector.analyze_compliance(detections)
                        # Tag violations with camera
                        if compliance.get('violations'):
                            # Log with camera association in DB if needed
                            tracker.update(compliance, datetime.now())
                            # Also try to save Violation with camera FK (if tracker would do? We'll do extra)
                            try:
                                from .models import Violation as V
                                for v in compliance['violations']:
                                    V.objects.create(
                                        person_id=str(v['person_id']),
                                        missing_items=v['missing_items'],
                                        violation_type='DETECTED',
                                        camera=cam,
                                        timestamp=timezone.now()
                                    )
                            except: pass
                        frame = detector.annotate_frame(frame, detections, compliance)
                        # Add camera name overlay
                        cv2.putText(frame, f"{cam.name} ({cam.ip_address})", (10, frame.shape[0]-15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255),1, cv2.LINE_AA)
                        cv2.putText(frame, f"{'DETECT ON' if cam.detection_enabled else 'DETECT OFF'}", (frame.shape[1]-140, frame.shape[0]-15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0) if cam.detection_enabled else (0,0,255),1)
                    except Exception as e:
                        logger.warning(f"camera stream detect error: {e}")
                # Encode
                ret2, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ret2:
                    continue
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                time.sleep(0.04)  # ~25 fps cap
        finally:
            cap.release()

    return StreamingHttpResponse(gen(), content_type='multipart/x-mixed-replace; boundary=frame')

@csrf_exempt
def ip_camera_bulk_add(request):
    """Bulk add IP addresses from textarea"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    form = BulkIPForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
    raw = form.cleaned_data['ips']
    protocol = form.cleaned_data['protocol']
    location = form.cleaned_data.get('location') or ''
    conf = form.cleaned_data.get('confidence_threshold') or 0.6

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    created = []
    errors = []
    for line in lines:
        try:
            # Parse various formats
            # If line contains :// then it's full URL
            ip = None
            port = None
            path = "/stream1"
            username = ""
            password = ""
            name = ""

            # Try to extract via regex for full url
            m = re.match(r'^(?:(?P<proto>rtsp|http|https)://)?(?:(?P<user>[^:]+):(?P<pass>[^@]+)@)?(?P<host>[^:/\s]+)(?::(?P<port>\d+))?(?P<path>/\S*)?', line)
            if m and m.group('host'):
                host = m.group('host')
                ip = host
                if m.group('port'):
                    port = int(m.group('port'))
                else:
                    port = 554 if protocol.startswith('rtsp') else (443 if protocol=='https' else 80)
                if m.group('path'):
                    path = m.group('path')
                if m.group('user'):
                    username = m.group('user')
                if m.group('pass'):
                    password = m.group('pass')
                if m.group('proto'):
                    protocol_eff = m.group('proto')
                    # map to our choices
                    if protocol_eff not in dict(IPCamera.PROTOCOL_CHOICES):
                        protocol_eff = protocol
                else:
                    protocol_eff = protocol
            else:
                # simple IP
                ip = line
                port = 554
                path = "/stream1"
                protocol_eff = protocol

            # Validate IP/host
            try:
                ipaddress.ip_address(ip)
            except:
                # allow hostname
                if '.' not in ip:
                    raise ValueError("Invalid IP/hostname")

            # Auto-name from IP
            name = f"Cam-{ip.replace('.','-')}"
            # Check existing
            if IPCamera.objects.filter(ip_address=ip, port=port, stream_path=path).exists():
                errors.append(f"{line}: already exists")
                continue

            cam = IPCamera.objects.create(
                name=name,
                ip_address=ip,
                port=port,
                protocol=protocol_eff,
                stream_path=path,
                username=username,
                password=password,
                location=location,
                confidence_threshold=conf,
                is_active=True,
                detection_enabled=True,
            )
            created.append({'id': cam.id, 'name': cam.name, 'ip': cam.ip_address})
        except Exception as e:
            errors.append(f"{line}: {e}")

    return JsonResponse({'ok': True, 'created': created, 'errors': errors, 'count': len(created)})

def api_camera_list(request):
    cams = IPCamera.objects.all().order_by('name')
    data = []
    for c in cams:
        data.append({
            'id': c.id,
            'name': c.name,
            'ip_address': c.ip_address,
            'port': c.port,
            'protocol': c.protocol,
            'stream_path': c.stream_path,
            'stream_url': c.display_url,
            'location': c.location,
            'is_active': c.is_active,
            'detection_enabled': c.detection_enabled,
            'status': c.status,
            'last_seen': c.last_seen.isoformat() if c.last_seen else None,
            'confidence_threshold': c.confidence_threshold,
        })
    return JsonResponse({'cameras': data, 'count': len(data)})

def api_camera_detail(request, pk):
    try:
        c = IPCamera.objects.get(pk=pk)
        return JsonResponse({
            'id': c.id,
            'name': c.name,
            'ip_address': c.ip_address,
            'port': c.port,
            'protocol': c.protocol,
            'stream_path': c.stream_path,
            'stream_url': c.display_url,
            'full_url': c.stream_url,
            'location': c.location,
            'is_active': c.is_active,
            'detection_enabled': c.detection_enabled,
            'status': c.status,
            'last_seen': c.last_seen.isoformat() if c.last_seen else None,
            'confidence_threshold': c.confidence_threshold,
        })
    except IPCamera.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
