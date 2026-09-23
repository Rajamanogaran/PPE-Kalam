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

# ---------- IP Camera Management — Industry Standard ----------
import re
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.contrib.auth.decorators import login_required

def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")

def _audit(request, action, entity, entity_id, detail=None):
    """Immutable audit trail (industry: who did what, when, from where)"""
    try:
        from .models import AuditLog
        AuditLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            detail=detail or {},
            ip_address=_get_client_ip(request),
        )
    except Exception as e:
        logger.warning(f"audit log failed: {e}")

def _require_write(request):
    """In DEBUG allow anonymous for demo; in prod require staff. Returns JsonResponse on failure or None if ok."""
    if settings.DEBUG:
        return None
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    if not request.user.is_staff:
        return JsonResponse({"error": "Staff permission required"}, status=403)
    return None

def ip_camera_list(request):
    """Industry: filtered, searchable, paginated, zone-aware camera inventory with KPIs"""
    qs = IPCamera.objects.select_related("zone").all()
    # Filters
    q = request.GET.get("q", "").strip()
    zone_id = request.GET.get("zone")
    status = request.GET.get("status")
    proto = request.GET.get("protocol")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(ip_address__icontains=q) | Q(location__icontains=q) | Q(zone__name__icontains=q))
    if zone_id:
        qs = qs.filter(zone_id=zone_id)
    if status:
        qs = qs.filter(status=status)
    if proto:
        qs = qs.filter(protocol=proto)
    qs = qs.order_by("-is_active", "zone__name", "name")

    # KPIs (industry: total, active, error rate, uptime, detection coverage)
    total = IPCamera.objects.count()
    active = IPCamera.objects.filter(is_active=True).count()
    detection_on = IPCamera.objects.filter(detection_enabled=True, is_active=True).count()
    error = IPCamera.objects.filter(status="error").count()
    from django.db.models import Avg
    avg_uptime = IPCamera.objects.filter(is_active=True).aggregate(avg=Avg("uptime_24h"))["avg"] or 0

    # Pagination (industry: server-side, page_size via env)
    page_size = int(request.GET.get("page_size", settings.PPE_API_PAGE_SIZE))
    page_size = max(5, min(50, page_size))
    paginator = Paginator(qs, page_size)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Zones for filter + form
    from .models import CameraZone
    zones = CameraZone.objects.annotate(cam_count=Count("cameras")).order_by("name")

    form = IPCameraForm()
    bulk_form = BulkIPForm()
    # Patch bulk_form zone queryset to include zones
    bulk_form.fields["zone"].queryset = zones

    context = {
        "cameras": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "zones": zones,
        "q": q,
        "selected_zone": zone_id,
        "selected_status": status,
        "selected_protocol": proto,
        "stats": {
            "total": total,
            "active": active,
            "detection_on": detection_on,
            "error": error,
            "avg_uptime": round(avg_uptime, 1),
            "inactive": total - active,
        },
        "form": form,
        "bulk_form": bulk_form,
        "model_loaded": _model_status(),
        "active_page": "cameras",
    }
    return render(request, "monitor/cameras.html", context)

def ip_camera_create(request):
    err = _require_write(request)
    if err:
        # For AJAX, return JSON; for page, redirect to login
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return err
        from django.shortcuts import redirect
        return redirect(f"/admin/login/?next={request.path}")
    if request.method == "POST":
        form = IPCameraForm(request.POST)
        if form.is_valid():
            cam = form.save(commit=False)
            if request.user.is_authenticated:
                cam.created_by = request.user
                cam.updated_by = request.user
            try:
                cam.save()
                _audit(request, "create", "IPCamera", cam.pk, {"name": cam.name, "ip": cam.ip_address})
                logger.info(f"Camera created: {cam.name} {cam.ip_address} by {request.user}")
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"ok": True, "id": cam.id, "name": cam.name})
                messages.success(request, f"Camera '{cam.name}' added ({cam.ip_address}:{cam.port})")
                return render(request, "monitor/camera_form.html", {"form": IPCameraForm(), "created": cam, "active_page": "cameras", "model_loaded": _model_status()})
            except IntegrityError:
                form.add_error(None, "Camera with this IP:port:path already exists")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "errors": form.errors}, status=400)
        return render(request, "monitor/camera_form.html", {"form": form, "active_page": "cameras", "model_loaded": _model_status()})
    else:
        form = IPCameraForm()
    return render(request, "monitor/camera_form.html", {"form": form, "active_page": "cameras", "model_loaded": _model_status()})

def ip_camera_edit(request, pk):
    try:
        cam = IPCamera.objects.get(pk=pk)
    except IPCamera.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)
    if request.method == "POST":
        err = _require_write(request)
        if err and request.headers.get("x-requested-with") == "XMLHttpRequest":
            return err
        form = IPCameraForm(request.POST, instance=cam)
        if form.is_valid():
            cam = form.save(commit=False)
            if request.user.is_authenticated:
                cam.updated_by = request.user
            cam.save()
            _audit(request, "update", "IPCamera", cam.pk, {"name": cam.name})
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "id": cam.id})
            messages.success(request, f"Camera '{cam.name}' updated")
            return render(request, "monitor/camera_form.html", {"form": form, "camera": cam, "active_page": "cameras", "model_loaded": _model_status()})
        else:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "errors": form.errors}, status=400)
            return render(request, "monitor/camera_form.html", {"form": form, "camera": cam, "active_page": "cameras", "model_loaded": _model_status()})
    else:
        form = IPCameraForm(instance=cam)
        # Mask password for display: don't show encrypted value; form handles blank = keep
        return render(request, "monitor/camera_form.html", {"form": form, "camera": cam, "active_page": "cameras", "model_loaded": _model_status()})

@csrf_exempt
def ip_camera_delete(request, pk):
    if request.method not in ("POST", "DELETE"):
        return JsonResponse({"error": "Use POST/DELETE"}, status=405)
    err = _require_write(request)
    if err:
        return err
    try:
        cam = IPCamera.objects.get(pk=pk)
        name = cam.name
        ip = cam.ip_address
        cam.delete()
        _audit(request, "delete", "IPCamera", pk, {"name": name, "ip": ip})
        logger.info(f"Camera deleted: {name} ({ip}) by {request.user}")
        return JsonResponse({"ok": True, "name": name})
    except IPCamera.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

@csrf_exempt
def ip_camera_toggle(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    err = _require_write(request)
    if err:
        return err
    try:
        cam = IPCamera.objects.get(pk=pk)
        field = request.POST.get("field", "is_active")
        if field not in ("is_active", "detection_enabled"):
            field = "is_active"
        setattr(cam, field, not getattr(cam, field))
        if request.user.is_authenticated:
            cam.updated_by = request.user
        cam.save(update_fields=[field, "updated_at", "updated_by"] if hasattr(cam, "updated_by") else [field, "updated_at"])
        _audit(request, "toggle", "IPCamera", cam.pk, {"field": field, "value": getattr(cam, field)})
        return JsonResponse({"ok": True, "field": field, "value": getattr(cam, field)})
    except IPCamera.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

def ip_camera_test(request, pk):
    try:
        cam = IPCamera.objects.select_related("zone").get(pk=pk)
    except IPCamera.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Not found"}, status=404)
    import time as _t
    start = _t.time()
    ok, msg = cam.test_connection(timeout=5)
    latency = int((_t.time() - start) * 1000) if ok else None
    # Use record_health to update uptime + health log (industry)
    try:
        cam.record_health(ok, msg)
        # Also store latency in latest health log
        if latency and ok:
            from .models import CameraHealthLog
            # Update last log's latency
            last = CameraHealthLog.objects.filter(camera=cam).order_by("-checked_at").first()
            if last:
                last.latency_ms = latency
                last.save(update_fields=["latency_ms"])
    except Exception as e:
        logger.warning(f"record_health failed: {e}")
        # Fallback old behavior
        cam.status = "active" if ok else "error"
        cam.last_error = "" if ok else msg[:500]
        if ok:
            cam.last_seen = timezone.now()
        cam.save(update_fields=["status", "last_error", "last_seen", "updated_at"])
    _audit(request, "test", "IPCamera", cam.pk, {"ok": ok, "latency_ms": latency, "msg": msg[:200]})
    return JsonResponse({"ok": ok, "message": msg, "status": cam.status, "url": cam.display_url, "latency_ms": latency, "uptime_24h": cam.uptime_24h})

def ip_camera_snapshot(request, pk):
    """Return a single JPEG snapshot from the IP camera with optional PPE overlay (industry: short timeout, audit)"""
    try:
        cam = IPCamera.objects.get(pk=pk)
    except IPCamera.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)
    if not HAS_CV2:
        return JsonResponse({"error": "OpenCV not available"}, status=500)
    detect = request.GET.get("detect", "1") == "1"
    try:
        cap = cv2.VideoCapture(cam.stream_url)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
        if not cap.isOpened():
            cam.record_health(False, f"Cannot open {cam.display_url}")
            return JsonResponse({"error": f"Cannot open {cam.display_url} (check IP/port/path/auth)"}, status=502)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            cam.record_health(False, "No frame received")
            return JsonResponse({"error": "No frame received (stream ok but no data - codec/auth)"}, status=502)
        cam.record_health(True, "snapshot ok")
        if detect and cam.detection_enabled:
            try:
                cfg = PPEConfig()
                cfg.CONFIDENCE_THRESHOLD = cam.confidence_threshold
                from .utils.detector import PPEDetector
                detector = PPEDetector(cfg)
                detections = detector.detect(frame)
                compliance = detector.analyze_compliance(detections)
                frame = detector.annotate_frame(frame, detections, compliance)
            except Exception as e:
                logger.warning(f"Snapshot detect failed: {e}")
        ret2, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ret2:
            return JsonResponse({"error": "Encode failed"}, status=500)
        return HttpResponse(buf.tobytes(), content_type="image/jpeg")
    except Exception as e:
        logger.exception("snapshot error")
        return JsonResponse({"error": str(e)[:500]}, status=500)

def ip_camera_stream(request, pk):
    """MJPEG stream from IP camera with live PPE detection overlay (industry: per-camera config, violation FK, throttled)"""
    try:
        cam = IPCamera.objects.select_related("zone").get(pk=pk)
    except IPCamera.DoesNotExist:
        return HttpResponse("Camera not found", status=404)
    if not HAS_CV2:
        return HttpResponse("OpenCV not installed", status=500)

    def gen():
        import os
        if cam.protocol == "rtsp_tcp":
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        cap = cv2.VideoCapture(cam.stream_url)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 7000)
        if not cap.isOpened():
            err = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(err, f"Cannot open {cam.display_url}", (20, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.putText(err, "Check IP/port/path/auth/firewall", (20, 270), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            ret, buf = cv2.imencode(".jpg", err)
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
            cam.record_health(False, "stream open failed")
            return
        cfg = PPEConfig()
        cfg.CONFIDENCE_THRESHOLD = cam.confidence_threshold
        try:
            from .utils.detector import PPEDetector
            detector = PPEDetector(cfg)
        except Exception:
            detector = get_detector()
        tracker = get_tracker()
        try:
            while True:
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(0.1)
                    continue
                if cam.detection_enabled:
                    try:
                        detections = detector.detect(frame)
                        compliance = detector.analyze_compliance(detections)
                        if compliance.get("violations"):
                            tracker.update(compliance, datetime.now())
                            # Persist with FK (industry: zone denormalized)
                            try:
                                from .models import Violation as V
                                for v in compliance["violations"]:
                                    V.objects.create(
                                        person_id=str(v["person_id"]),
                                        missing_items=v["missing_items"],
                                        violation_type="DETECTED",
                                        camera=cam,
                                        zone=cam.zone,
                                        timestamp=timezone.now(),
                                    )
                            except Exception as e:
                                logger.warning(f"violation FK save failed: {e}")
                        frame = detector.annotate_frame(frame, detections, compliance)
                        cv2.putText(frame, f"{cam.name} ({cam.ip_address})", (10, frame.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
                        cv2.putText(frame, f"{'DETECT ON' if cam.detection_enabled else 'DETECT OFF'}", (frame.shape[1] - 140, frame.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0) if cam.detection_enabled else (0, 0, 255), 1)
                    except Exception as e:
                        logger.warning(f"camera stream detect error: {e}")
                ret2, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ret2:
                    continue
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
                time.sleep(0.04)
        finally:
            cap.release()

    return StreamingHttpResponse(gen(), content_type="multipart/x-mixed-replace; boundary=frame")

@csrf_exempt
def ip_camera_bulk_add(request):
    """Bulk add IP addresses from textarea (industry: validated, audited, zone-aware, idempotent)"""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    err = _require_write(request)
    if err:
        return err
    form = BulkIPForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)
    raw = form.cleaned_data["ips"]
    protocol = form.cleaned_data["protocol"]
    zone = form.cleaned_data.get("zone")
    location = form.cleaned_data.get("location") or (zone.name if zone else "")
    conf = form.cleaned_data.get("confidence_threshold") or 0.6

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    created = []
    errors = []
    for line in lines:
        try:
            ip = None
            port = None
            path = "/stream1"
            username = ""
            password = ""
            m = re.match(r"^(?:(?P<proto>rtsp|http|https)://)?(?:(?P<user>[^:]+):(?P<pass>[^@]+)@)?(?P<host>[^:/\s]+)(?::(?P<port>\d+))?(?P<path>/\S*)?", line)
            if m and m.group("host"):
                host = m.group("host")
                ip = host
                if m.group("port"):
                    port = int(m.group("port"))
                else:
                    port = 554 if protocol.startswith("rtsp") else (443 if protocol == "https" else 80)
                if m.group("path"):
                    path = m.group("path")
                if m.group("user"):
                    username = m.group("user")
                if m.group("pass"):
                    password = m.group("pass")
                if m.group("proto"):
                    protocol_eff = m.group("proto")
                    if protocol_eff not in dict(IPCamera.PROTOCOL_CHOICES):
                        protocol_eff = protocol
                else:
                    protocol_eff = protocol
            else:
                ip = line
                port = 554
                path = "/stream1"
                protocol_eff = protocol

            # Validate
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                # hostname check (form already validated bulk, but re-check)
                if "." not in ip and ip != "localhost":
                    raise ValueError("Invalid IP/hostname")
            if IPCamera.objects.filter(ip_address=ip, port=port, stream_path=path).exists():
                errors.append(f"{line}: already exists")
                continue
            name = f"Cam-{ip.replace('.', '-').replace(':', '-')}-{port}"
            # Ensure unique name
            base = name
            i = 1
            while IPCamera.objects.filter(name=name).exists():
                name = f"{base}-{i}"
                i += 1
            cam = IPCamera.objects.create(
                name=name,
                zone=zone,
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
                created_by=request.user if request.user.is_authenticated else None,
                updated_by=request.user if request.user.is_authenticated else None,
            )
            created.append({"id": cam.id, "name": cam.name, "ip": cam.ip_address, "url": cam.display_url})
        except Exception as e:
            logger.warning(f"bulk line failed {line}: {e}")
            errors.append(f"{line}: {e}")
    if created:
        _audit(request, "create", "IPCamera", "bulk", {"created": len(created), "ips": [c["ip"] for c in created]})
    return JsonResponse({"ok": True, "created": created, "errors": errors, "count": len(created)})

def api_camera_list(request):
    qs = IPCamera.objects.select_related("zone").all().order_by("name")
    # Filtering via query params (industry: ?q=&zone=&status=&protocol=)
    q = request.GET.get("q")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(ip_address__icontains=q) | Q(zone__name__icontains=q))
    zone = request.GET.get("zone")
    if zone:
        qs = qs.filter(zone_id=zone)
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    # Pagination
    try:
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("page_size", settings.PPE_API_PAGE_SIZE))
    except:
        page, page_size = 1, settings.PPE_API_PAGE_SIZE
    page_size = max(5, min(50, page_size))
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)
    data = []
    for c in page_obj:
        data.append({
            "id": c.id,
            "name": c.name,
            "zone": c.zone.name if c.zone else None,
            "zone_id": c.zone_id,
            "ip_address": c.ip_address,
            "port": c.port,
            "protocol": c.protocol,
            "stream_path": c.stream_path,
            "stream_url": c.display_url,
            "location": c.location,
            "is_active": c.is_active,
            "detection_enabled": c.detection_enabled,
            "status": c.status,
            "uptime_24h": c.uptime_24h,
            "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            "confidence_threshold": c.confidence_threshold,
        })
    return JsonResponse({"cameras": data, "count": paginator.count, "page": page_obj.number, "pages": paginator.num_pages, "page_size": page_size})

def api_camera_detail(request, pk):
    try:
        c = IPCamera.objects.select_related("zone").get(pk=pk)
        return JsonResponse({
            "id": c.id,
            "name": c.name,
            "zone": c.zone.name if c.zone else None,
            "ip_address": c.ip_address,
            "port": c.port,
            "protocol": c.protocol,
            "stream_path": c.stream_path,
            "stream_url": c.display_url,
            "full_url": c.stream_url if request.user.is_staff else c.display_url,  # hide plain password unless staff
            "location": c.location,
            "is_active": c.is_active,
            "detection_enabled": c.detection_enabled,
            "status": c.status,
            "uptime_24h": c.uptime_24h,
            "consecutive_failures": c.consecutive_failures,
            "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            "last_error": c.last_error,
            "confidence_threshold": c.confidence_threshold,
        })
    except IPCamera.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)
