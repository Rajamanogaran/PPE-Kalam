"""
Industry: periodic health check for IP cameras — for cron, systemd, or Celery beat.
Usage: python manage.py check_cameras [--loop --interval 60]
"""
import time
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Check all active IP cameras and update health logs (for SLA/uptime)"

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Run forever, checking every --interval seconds")
        parser.add_argument("--interval", type=int, default=60, help="Seconds between checks in --loop mode (default 60)")
        parser.add_argument("--timeout", type=int, default=5, help="Per-camera timeout seconds (default 5)")
        parser.add_argument("--ids", nargs="*", type=int, help="Only check these camera IDs")

    def handle(self, *args, **opts):
        from monitor.models import IPCamera

        loop = opts["loop"]
        interval = opts["interval"]
        timeout = opts["timeout"]
        ids = opts.get("ids")

        def one_run():
            qs = IPCamera.objects.filter(is_active=True)
            if ids:
                qs = qs.filter(id__in=ids)
            qs = qs.select_related("zone")
            if not qs.exists():
                self.stdout.write(self.style.WARNING("No active cameras"))
                return
            self.stdout.write(f"Checking {qs.count()} cameras (timeout {timeout}s)...")
            for cam in qs:
                start = time.time()
                ok, msg = cam.test_connection(timeout=timeout)
                latency = int((time.time() - start) * 1000) if ok else None
                try:
                    cam.record_health(ok, msg)
                    if latency and ok:
                        # patch latency into last log
                        from monitor.models import CameraHealthLog
                        last = CameraHealthLog.objects.filter(camera=cam).order_by("-checked_at").first()
                        if last and last.latency_ms is None:
                            last.latency_ms = latency
                            last.save(update_fields=["latency_ms"])
                    status = self.style.SUCCESS("OK") if ok else self.style.ERROR("FAIL")
                    self.stdout.write(f"  {status} {cam.name} ({cam.ip_address}:{cam.port}) — {msg} {latency or ''}ms — up {cam.uptime_24h}%")
                except Exception as e:
                    logger.exception(f"record_health {cam.name} failed: {e}")

        if loop:
            self.stdout.write(self.style.NOTICE(f"Loop mode: checking every {interval}s. Ctrl+C to stop."))
            try:
                while True:
                    one_run()
                    time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write("Stopped.")
        else:
            one_run()
