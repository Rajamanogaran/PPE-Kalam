# 🏭 PPE Kalam — Real-Time Industrial PPE Compliance Monitoring (Django)

> **Django port** of the original Streamlit `ppe-compliance-monitor`. Same YOLOv10 + ByteTrack computer-vision core, now production-ready with Django 4.2, REST APIs, persistent storage, admin, and a modern responsive UI.
>
> Original Streamlit entry: `app.py` → Django: `monitor/views.py` + `templates/` + `static/`

![Django](https://img.shields.io/badge/Django-4.2-092E20?style=for-the-badge&logo=django)
![YOLO](https://img.shields.io/badge/YOLOv10-Ultralytics-00D9FF?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python)
![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)

---

## ✨ Features

- **Real-time Detection** — YOLOv10 (or `yolov10n` fallback) for `helmet`, `safety_vest`, `gloves`, `industrial_shoes`, `person`
- **Multi-person Tracking** — ByteTrack (via `supervision`) with persistent IDs
- **Compliance Engine** — IoU + centre-containment association, violation buffering (3-frame consistency)
- **Live Monitoring** — Browser `getUserMedia` → `POST /api/process-frame/` (replaces `streamlit-webrtc` + `aiortc`)
- **Upload** — Image & video upload with annotated result preview and download
- **Dashboard** — Plotly charts: violation trend, missing-item pie/bar, compliance gauge, CSV export
- **IP Camera Management** — Add/edit/list of IP addresses for detection: RTSP/HTTP/MJPEG, bulk import, per-camera confidence, live MJPEG with PPE overlay, snapshot & test connection
- **Violation Log** — Dual store: `logs/violations.csv` (Streamlit compatible) + Django ORM (`monitor.Violation` with `camera` FK)
- **Admin** — `/admin/` for IP cameras, violations, sessions, user management
- **API First** — REST endpoints for any camera/PLC/app integration

## 🔄 Streamlit → Django Mapping

| Streamlit | Django |
|-----------|--------|
| `app.py` (single file, `st.*`) | `ppe_project/settings.py` + `monitor/views.py` + `templates/base.html` & `monitor/*.html` |
| `streamlit-webrtc` `VideoProcessor.recv()` | Browser `getUserMedia` + `static/js/live_monitor.js` → `POST /api/process-frame/` |
| `st.slider` / `st.metric` sidebar | Bootstrap 5 + `static/css/style.css` metric cards + range inputs in `live.html` |
| `st.plotly_chart` | Plotly CDN + `dashboard.js` |
| `ViolationTracker` CSV only | `monitor/utils/violation_tracker.py` (CSV) + `monitor/models.py` (`Violation`, `DetectionSession`) |
| `pip install -r requirements.txt` + `streamlit run app.py` | `pip install -r requirements.txt` + `python manage.py migrate` + `python manage.py runserver` |
| `utils/config.py`, `detector.py`, `violation_tracker.py` | `monitor/utils/{config,detector,violation_tracker}.py` (kept, adapted for Django singleton lazy load) |
| `models/download_models.py` | `python manage.py download_models` (management command) |

All original `utils/` **logic is preserved** — only imports & singleton handling changed to suit Django's process model.

---

## 🗂️ Project Structure

```
ppe-compliance-monitor/
├── manage.py
├── run.py                      # convenience launcher (python run.py)
├── requirements.txt
├── ppe_project/
│   ├── settings.py             # Django 4.2 settings (ALLOWED_HOSTS='*', X_FRAME_OPTIONS=ALLOWALL for preview)
│   ├── urls.py
│   ├── wsgi.py / asgi.py
├── monitor/
│   ├── models.py               # IPCamera, Violation (with camera FK), DetectionSession
│   ├── views.py                # index, live, dashboard, violations, upload + 5 API endpoints + 9 IP-camera views
│   ├── urls.py
│   ├── forms.py                # Image/Video + IPCameraForm, BulkIPForm
│   ├── admin.py                # IPCameraAdmin, ViolationAdmin
│   ├── utils/
│   │   ├── config.py           # PPEConfig, UIConfig (dataclasses)
│   │   ├── detector.py         # PPEDetector + get_detector() singleton, YOLOv10 + ByteTrack
│   │   └── violation_tracker.py# ViolationTracker + get_tracker() singleton
│   ├── management/commands/download_models.py
│   └── templates/monitor/
│       ├── index.html          # overview + quick test + charts
│       ├── live.html           # webcam live monitoring
│       ├── cameras.html        # IP camera list, bulk add, live grid, snapshot modal
│       ├── camera_form.html    # add/edit single camera
│       ├── dashboard.html      # analytics deep-dive
│       ├── violations.html     # log table
│       └── upload.html         # image/video upload
├── templates/base.html         # Bootstrap 5 navbar, footer, live-dot, clock
├── static/
│   ├── css/style.css           # Ported + expanded from Streamlit style.css
│   └── js/
│       ├── dashboard.js        # auto-refresh polling
│       └── live_monitor.js     # webcam capture loop
├── ml_models/.gitkeep          # put ppe_yolov10n.pt here (or auto-downloads yolov10n.pt)
├── logs/.gitkeep               # violations.csv auto-created
├── media/.gitkeep              # uploads & annotated results
└── README.md
```

---

## 🛠️ Installation

### 1. Clone & venv (recommended)
```bash
git clone <your-fork> 
cd ppe-compliance-monitor
python -m venv ppe_env
source ppe_env/bin/activate  # Windows: ppe_env\Scripts\activate
```

### 2. Install deps
```bash
pip install -r requirements.txt
```
> For CPU-only PyTorch you may prefer `pip install torch --index-url https://download.pytorch.org/whl/cpu` before the rest.

### 3. DB & models
```bash
python manage.py migrate
python manage.py download_models          # downloads yolov10n.pt (fallback) or uses ml_models/ppe_yolov10n.pt
# optional: create admin
python manage.py createsuperuser
```

### 4. Run
```bash
python manage.py runserver 0.0.0.0:8000
# or: python run.py
# open http://localhost:8000
```

Preview on Arena/E2B: server binds `0.0.0.0` and allows `*.e2b.app` CSRF/iframe — just open the LIVE PREVIEW URL.

---

## 🔌 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/` | Overview (index) |
| `GET`  | `/live/` | Live webcam page |
| `GET`  | `/dashboard/?hours=24` | Analytics (query `hours`) |
| `GET`  | `/violations/?limit=50` | Log table |
| `GET/POST` | `/upload/` | Image/video upload form |
| `GET`  | `/api/health/` | `{status, model_loaded, timestamp}` |
| `POST` | `/api/process-frame/` | JSON `{image: "data:image/jpeg;base64,...", confidence:0.6}` → `{annotated_image, compliance, stats}` |
| `POST` | `/api/detect-image/` | multipart `image` file → `{annotated_image (base64), annotated_url, compliance}` |
| `GET`  | `/api/stats/?hours=24` | Violation stats JSON |
| `GET`  | `/api/violations/?limit=20` | Recent violations JSON |
| `GET`  | `/cameras/` | IP camera list + bulk add + live grid |
| `GET`  | `/cameras/<id>/stream/` | MJPEG stream from IP camera with PPE overlay |
| `GET`  | `/cameras/<id>/snapshot/?detect=1` | Single JPEG snapshot (annotated if detect=1) |
| `POST` | `/cameras/bulk-add/` | Bulk add IPs: `ips` textarea + `protocol`, one per line (supports `192.168.1.10:554/stream1`, `rtsp://user:pass@host/live/ch1`) |
| `GET`  | `/api/cameras/` | List all cameras JSON |
| `GET`  | `/api/cameras/<id>/` | Detail JSON |
| `GET`  | `/api/video-feed/` | MJPEG stream (server cam 0 if present) |
| `GET`  | `/api/export-csv/` | Download `violations.csv` |

**Example — frame processing:**
```bash
curl -X POST http://localhost:8000/api/process-frame/ \
  -H "Content-Type: application/json" \
  -d '{"image":"data:image/jpeg;base64,'$(base64 -w0 test.jpg)'","confidence":0.6}'
```

**Example — image upload:**
```bash
curl -X POST http://localhost:8000/api/detect-image/ -F image=@site.jpg -F confidence=0.5
```

---

## ⚙️ Configuration

Edit `monitor/utils/config.py` or pass per-request overrides:

- `PPEConfig.CONFIDENCE_THRESHOLD` (default 0.6)
- `PPEConfig.IOU_THRESHOLD` (0.5)
- `PPEConfig.IMG_SIZE` (640)
- `PPEConfig.REQUIRED_PPE = ['helmet','safety_vest','gloves','industrial_shoes']`
- Live page sliders POST `confidence` to APIs.

Env vars in `ppe_project/settings.py`:
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`

Colours (BGR for OpenCV, hex for CSS) live in `PPEConfig.COLOR_PALETTE` + `static/css/style.css`.

---

## 🧪 Training Your Own PPE Model

1. Label dataset with classes `helmet`, `safety_vest`, `gloves`, `industrial_shoes`, `person` (Roboflow, CVAT, etc.)
2. Train YOLOv10:
   ```bash
   yolo detect train data=ppe.yaml model=yolov10n.pt epochs=100 imgsz=640
   ```
3. Copy best weight:
   ```bash
   cp runs/detect/train/weights/best.pt ml_models/ppe_yolov10n.pt
   ```
4. Restart server — detector will prefer `ml_models/ppe_yolov10n.pt`.

Without a custom weight the app still works: COCO `person` is detected; PPE items will naturally be missing → violations illustrate the flow (good for demos).

---

## 📹 IP Camera Usage

Add cameras via UI (`/cameras/` → **Add Camera** / **Bulk Add IPs**) or API/admin:

**Supported URL formats:**
- `192.168.1.64` → `rtsp://192.168.1.64:554/stream1` (default)
- `192.168.1.64:8080/video.mjpg` → HTTP MJPEG
- `rtsp://admin:pass@10.0.0.5:554/live/ch1` (full RTSP with auth)
- `10.0.0.10:554/Streaming/Channels/101` (Hikvision)
- Protocol choice: `rtsp`, `rtsp_tcp` (forces TCP transport), `http`, `https`

**Bulk add example:** paste into Bulk Add modal:
```
192.168.1.10:554/stream1
192.168.1.11:554/stream1
10.0.0.5:8080/video.mjpg
rtsp://admin:12345@192.168.1.100:554/live/ch1
```

**APIs:**
```bash
curl http://localhost:8000/api/cameras/
curl -X POST http://localhost:8000/cameras/bulk-add/ -d "ips=192.168.1.64%0A192.168.1.65&protocol=rtsp&location=Workshop"
# Test connection
curl http://localhost:8000/cameras/1/test/
# MJPEG stream with detection (open in browser / VLC)
http://localhost:8000/cameras/1/stream/
# Snapshot
curl http://localhost:8000/cameras/1/snapshot/?detect=1 -o snap.jpg
```

Each camera has per-camera `confidence_threshold` and `detection_enabled` toggle; violations are FK-linked to `IPCamera` for zone analytics.

## 🐳 Deployment

- **Static:** `python manage.py collectstatic`
- **Prod:** set `DJANGO_DEBUG=False`, provide `DJANGO_SECRET_KEY`, put behind `gunicorn ppe_project.wsgi`.
- **Docker:** `FROM python:3.11-slim` + `RUN pip install -r requirements.txt` + `CMD ["gunicorn", "ppe_project.wsgi:application"]`
- **Media:** configure `MEDIA_ROOT` to persistent volume.

---

## 📝 Original Streamlit Quick-Start (for comparison)

```bash
pip install -r requirements.txt
python models/download_models.py
streamlit run app.py
# http://localhost:8501
```

Django achieves the same in 3 commands with far more extensibility.

---

## 🤝 Contributing

PRs welcome — please run `python manage.py check` and keep `utils/` logic backward-compatible with the Streamlit version.

## 📄 License

MIT — see original repo.

---

*Generated for Arena — Django 4.2 port, 2026-09-23*
