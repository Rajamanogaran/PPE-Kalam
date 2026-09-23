# PPE-Kalam

**Industrial PPE Compliance Monitoring** — Real-time YOLOv10 + ByteTrack system for detecting helmets, safety vests, gloves & industrial shoes.

## 📁 Project

Django port lives in [`ppe-compliance-monitor/`](ppe-compliance-monitor/) — migrated from the original Streamlit prototype (see `ppe-compliance-monitor/README.md` for full docs).

**Quick start (Django):**
```bash
cd ppe-compliance-monitor
pip install -r requirements.txt
python manage.py migrate
python manage.py download_models
python manage.py runserver 0.0.0.0:8000
# open http://localhost:8000
```

**Original Streamlit (archived logic)**
- `app.py` → `monitor/views.py`
- `utils/detector.py` → `monitor/utils/detector.py` (same CV core, now Django singleton)
- `utils/violation_tracker.py` → `monitor/utils/violation_tracker.py` (CSV + Django ORM)
- `utils/config.py` → `monitor/utils/config.py`
- `models/download_models.py` → `python manage.py download_models`

See [`ppe-compliance-monitor/README.md`](ppe-compliance-monitor/README.md) for Streamlit→Django mapping, API docs & training guide.
