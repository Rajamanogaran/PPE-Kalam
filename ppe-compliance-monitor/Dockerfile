# Industry: multi-stage, slim, non-root, healthcheck, gunicorn
FROM python:3.11-slim as base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps for opencv + postgres
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first for cache
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App
COPY . .

# Collect static (ignore if fails in build without DB)
RUN python manage.py collectstatic --noinput || true

# Non-root user (industry: least privilege)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck (industry: k8s liveness)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -f http://localhost:8000/api/health/ || exit 1

# Gunicorn (industry: prod WSGI)
CMD ["gunicorn", "ppe_project.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
