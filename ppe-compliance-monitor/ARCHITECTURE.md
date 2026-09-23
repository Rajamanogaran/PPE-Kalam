# Architecture — PPE Kalam (Industry Standard)

## Overview
```
Browser (getUserMedia / IP Camera RTSP) → Django → YOLOv10 + ByteTrack → Compliance Engine → ViolationTracker (CSV + ORM) → Dashboard (Plotly) + AuditLog + HealthLog
```

## Components
- **ppe_project/settings.py** — 12-factor, env-driven, `django-environ` + `dj-database-url`, secure headers, WhiteNoise, Redis cache, Fernet encryption, structured logging (stdout).
- **monitor/models.py** — `CameraZone`, `IPCamera` (encrypted password, health fields, zone FK, audit FKs), `CameraHealthLog` (SLA), `Violation` (camera+zone FK), `DetectionSession`, `AuditLog`.
- **monitor/utils/detector.py** — Singleton `PPEDetector` wrapping Ultralytics YOLOv10, ByteTrack, mock fallback. Per-camera `PPEConfig` (confidence).
- **monitor/utils/violation_tracker.py** — 3-frame consistency buffer, CSV + ORM dual write, stats (trend, uptime, compliance rate).
- **monitor/views.py** — Page views + JSON APIs + IP camera fleet (filtered/paginated, audited, health-aware). `record_health()` updates `uptime_24h` + `CameraHealthLog`.
- **monitor/management/commands/check_cameras.py** — Cron/beat health checker (loop mode).
- **static/** — Bootstrap 5 + Plotly, `live_monitor.js` (capture loop), `dashboard.js` (polling).
- **Dockerfile** — slim, non-root, gunicorn, healthcheck; **docker-compose.yml** — web+postgres+redis.
- **.github/workflows/ci.yml** — check, migrate, test, docker build, flake8/black.

## Data Flow (IP Camera)
1. Admin adds `IPCamera` via `/cameras/` (form validates IP/host, port 1-65535, path `^/.*`, zone, creds encrypted).
2. `GET /cameras/<id>/test/` → `IPCamera.test_connection()` (cv2.VideoCapture, 5s timeout) → `record_health()` → `CameraHealthLog` + `uptime_24h` + `AuditLog`.
3. `GET /cameras/<id>/stream/` → MJPEG gen: `VideoCapture(stream_url)` → per-frame `PPEDetector` (camera confidence) → `Violation` FK + `zone` → `annotate_frame` → yield JPEG.
4. `GET /cameras/<id>/snapshot/?detect=1` → single frame with same pipeline.
5. Bulk import: `POST /cameras/bulk-add/` parses `rtsp://user:pass@host:port/path` or `IP:port/path`, idempotent (skip existing `IP:port/path`), audited.

## Security
- Passwords: `Fernet` (`PPE_FERNET_KEY`) at rest, `display_url` masks, `full_url` only for staff via API.
- Auth: `_require_write()` — DEBUG allows anonymous (demo), prod requires `is_staff` (RBAC ready). CSRF on all POST, `X-Frame-Options` DENY in prod, HSTS, `SESSION_COOKIE_SECURE`, `SECURE_PROXY_SSL_HEADER`.
- Audit: `AuditLog` immutable (user, action, entity, ip_address).
- Validation: `GenericIPAddressField` + hostname regex, `Min/MaxValueValidator`, `CheckConstraint` for port/conf, path traversal guard.

## Scalability
- DB: SQLite dev → Postgres via `DATABASE_URL` (prod). Cache: locmem → Redis via `REDIS_URL`.
- Gunicorn 3 workers, WhiteNoise static, `DATA_UPLOAD_MAX_MEMORY_SIZE` 50MB, `PPE_API_PAGE_SIZE` paginated.
- Health: `CameraHealthLog` + `uptime_24h`, `consecutive_failures` circuit-breaker (error after 3 fails).

## Observability
- Logging: verbose console, `monitor`/`ppe` loggers, health latency.
- Metrics: KPIs (fleet, online, detection coverage, avg uptime, error), Plotly trends, per-camera health, per-zone violations.
- Endpoints: `/api/health/`, `/api/cameras/?page=&q=&zone=&status=`, `/api/stats/?hours=`, `/api/violations/`.

## Deployment
- `make docker-build && make docker-up` or `gunicorn ppe_project.wsgi`.
- Env: `DJANGO_SECRET_KEY` (50+ chars), `PPE_FERNET_KEY` (`Fernet.generate_key()`), `DATABASE_URL`, `REDIS_URL`, `DJANGO_ALLOWED_HOSTS`.
- CI: GitHub Actions (check, migrate, test, docker, flake8).

## Future (industry roadmap)
- ONVIF discovery, PTZ, WebSocket streaming, Celery + Redis for async detection, Prometheus metrics, Grafana, S3 for media, Keycloak SSO, retention policy (30d health logs, 90d violations).
