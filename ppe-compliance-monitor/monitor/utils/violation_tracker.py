"""
Violation Tracker - Django port
Maintains CSV log + in-memory buffer for violation consistency.
Compatible with original Streamlit version; also integrates with Django ORM when available.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import os
import logging
import csv
from pathlib import Path

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None
    HAS_PANDAS = False

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    np = None
    HAS_NP = False

logger = logging.getLogger(__name__)

class ViolationTracker:
    def __init__(self, log_dir: str = None):
        if log_dir is None:
            # Default to Django settings if available
            try:
                from django.conf import settings
                log_dir = str(settings.PPE_LOGS_DIR)
            except:
                log_dir = "logs"

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize violation log
        self.violation_log_path = self.log_dir / "violations.csv"
        self._initialize_log()
        
        # Active violations tracking
        self.active_violations: Dict[str, Dict] = {}
        self.violation_buffer: Dict[str, List] = {}
        
    def _initialize_log(self):
        """Initialize violation log file"""
        if not self.violation_log_path.exists():
            if HAS_PANDAS:
                df = pd.DataFrame(columns=[
                    'timestamp', 'person_id', 'missing_items', 
                    'duration', 'violation_type', 'resolution_time'
                ])
                df.to_csv(self.violation_log_path, index=False)
            else:
                # CSV fallback without pandas
                with open(self.violation_log_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['timestamp','person_id','missing_items','duration','violation_type','resolution_time'])
            logger.info(f"Created violation log at {self.violation_log_path}")
    
    def update(self, compliance_data: Dict, frame_timestamp: datetime):
        """Update violation tracking with new compliance data"""
        current_violations = {}
        
        # Process current violations
        for violation in compliance_data.get('violations', []):
            person_id = violation['person_id']
            missing_items = violation['missing_items']
            violation_key = f"person_{person_id}"
            
            # Update violation buffer
            if violation_key not in self.violation_buffer:
                self.violation_buffer[violation_key] = []
            
            self.violation_buffer[violation_key].append({
                'timestamp': frame_timestamp,
                'missing_items': missing_items
            })
            
            # Keep only recent entries (5 sec window)
            buffer_window = frame_timestamp - timedelta(seconds=5)
            self.violation_buffer[violation_key] = [
                entry for entry in self.violation_buffer[violation_key]
                if entry['timestamp'] > buffer_window
            ]
            
            # Check if violation is consistent (at least 3 frames)
            if len(self.violation_buffer[violation_key]) >= 3:
                current_violations[violation_key] = {
                    'person_id': person_id,
                    'missing_items': missing_items,
                    'start_time': self.violation_buffer[violation_key][0]['timestamp'],
                    'last_seen': frame_timestamp
                }
        
        # Check for resolved violations
        resolved_violations = []
        for violation_key in list(self.active_violations.keys()):
            if violation_key not in current_violations:
                resolved_violations.append(self.active_violations[violation_key])
                del self.active_violations[violation_key]
                # Keep buffer for a while - clear after resolution
                if violation_key in self.violation_buffer:
                    # Keep one more cycle to avoid flicker, then clear
                    pass
        
        # Log resolved violations
        for resolved in resolved_violations:
            self._log_violation(resolved, resolved_violation=True)
            # Also try to create Django ORM entry if available
            self._log_to_db(resolved, resolved_violation=True)
        
        # Update active violations
        for violation_key, violation_data in current_violations.items():
            if violation_key in self.active_violations:
                # Update existing violation
                self.active_violations[violation_key]['last_seen'] = violation_data['last_seen']
                self.active_violations[violation_key]['missing_items'] = violation_data['missing_items']
            else:
                # New violation
                self.active_violations[violation_key] = violation_data
                self._log_violation(violation_data, resolved_violation=False)
                self._log_to_db(violation_data, resolved_violation=False)

    def _log_violation(self, violation_data: Dict, resolved_violation: bool = False):
        """Log violation to CSV"""
        try:
            timestamp = violation_data['last_seen' if resolved_violation else 'start_time']
            duration = (violation_data['last_seen'] - violation_data['start_time']).total_seconds()
            
            log_entry = {
                'timestamp': timestamp.isoformat(),
                'person_id': violation_data['person_id'],
                'missing_items': json.dumps(violation_data['missing_items']),
                'duration': duration if resolved_violation else None,
                'violation_type': 'RESOLVED' if resolved_violation else 'DETECTED',
                'resolution_time': violation_data['last_seen'].isoformat() if resolved_violation else None
            }
            
            if HAS_PANDAS:
                df = pd.DataFrame([log_entry])
                df.to_csv(self.violation_log_path, mode='a', header=False, index=False)
            else:
                with open(self.violation_log_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=['timestamp','person_id','missing_items','duration','violation_type','resolution_time'])
                    writer.writerow(log_entry)
        except Exception as e:
            logger.error(f"Failed to log violation to CSV: {e}")

    def _log_to_db(self, violation_data: Dict, resolved_violation: bool = False):
        """Optionally log to Django ORM if model exists"""
        try:
            from monitor.models import Violation
            from django.utils import timezone
            timestamp = violation_data['start_time']
            if timezone.is_naive(timestamp):
                timestamp = timezone.make_aware(timestamp)
            last_seen = violation_data['last_seen']
            if timezone.is_naive(last_seen):
                last_seen = timezone.make_aware(last_seen)

            Violation.objects.create(
                person_id=str(violation_data['person_id']),
                missing_items=violation_data['missing_items'],
                violation_type='RESOLVED' if resolved_violation else 'DETECTED',
                timestamp=timestamp,
                duration=(last_seen - timestamp).total_seconds() if resolved_violation else None,
                resolution_time=last_seen if resolved_violation else None
            )
        except Exception:
            # ORM may not be ready or migrated yet - silently ignore
            pass
    
    def get_violation_stats(self, hours: int = 24) -> Dict:
        """Get violation statistics for the specified time period"""
        try:
            if not self.violation_log_path.exists():
                return self._empty_stats()

            if not HAS_PANDAS:
                # Fallback without pandas: parse CSV manually but return minimal stats
                try:
                    with open(self.violation_log_path, encoding='utf-8') as f:
                        reader = list(csv.DictReader(f))
                    total = sum(1 for r in reader if r.get('violation_type')=='DETECTED')
                    resolved = sum(1 for r in reader if r.get('violation_type')=='RESOLVED')
                    return {
                        'total_violations': total,
                        'resolved_violations': resolved,
                        'active_violations': len(self.active_violations),
                        'common_missing_items': {},
                        'violation_trend': [],
                        'avg_resolution_time': 0,
                        'compliance_rate': 100.0 if total==0 else max(0, 100*(1-total/max(1,total+resolved))),
                        'recent_violations': reader[-10:][::-1]
                    }
                except Exception as e:
                    logger.warning(f"CSV fallback stats failed: {e}")
                    return self._empty_stats()

            df = pd.read_csv(self.violation_log_path)
            if df.empty:
                return self._empty_stats()

            # Parse timestamps
            try:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            except Exception:
                pass
            
            # Filter by time period
            cutoff_time = datetime.now() - timedelta(hours=hours)
            # Handle timezone naive vs aware
            try:
                recent_df = df[df['timestamp'] > cutoff_time]
            except:
                recent_df = df

            # If filter empties but hours large, fall back to all
            if recent_df.empty and len(df) > 0:
                recent_df = df.tail(200)
            
            stats = {
                'total_violations': len(recent_df[recent_df['violation_type'] == 'DETECTED']),
                'resolved_violations': len(recent_df[recent_df['violation_type'] == 'RESOLVED']),
                'active_violations': len(self.active_violations),
                'common_missing_items': self._get_common_missing_items(recent_df),
                'violation_trend': self._get_violation_trend(recent_df),
                'avg_resolution_time': self._get_avg_resolution_time(recent_df),
                'compliance_rate': self._get_compliance_rate(recent_df),
                'recent_violations': self._get_recent_violations(df, n=10)
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting violation stats: {e}")
            return self._empty_stats()

    def _empty_stats(self):
        return {
            'total_violations': 0,
            'resolved_violations': 0,
            'active_violations': len(self.active_violations),
            'common_missing_items': {},
            'violation_trend': [],
            'avg_resolution_time': 0,
            'compliance_rate': 100.0,
            'recent_violations': []
        }

    def _get_compliance_rate(self, df) -> float:
        try:
            if not HAS_PANDAS:
                return 100.0
            total = len(df[df['violation_type'] == 'DETECTED']) + len(df[df['violation_type'] == 'RESOLVED'])
            if total == 0:
                return 100.0
            detected = len(df[df['violation_type'] == 'DETECTED'])
            # Compliance = 1 - violations / total_observations (approx)
            return max(0, 100.0 * (1 - detected / max(1, total + detected)))
        except:
            return 100.0
    
    def _get_common_missing_items(self, df) -> Dict:
        """Get most commonly missing PPE items"""
        try:
            all_missing = []
            for items_json in df['missing_items'].dropna():
                try:
                    if isinstance(items_json, str):
                        items = json.loads(items_json)
                    else:
                        items = items_json
                    if isinstance(items, list):
                        all_missing.extend(items)
                except:
                    continue
            
            from collections import Counter
            return dict(Counter(all_missing).most_common())
        except:
            return {}
    
    def _get_violation_trend(self, df) -> List[Dict]:
        """Get violation trend over time"""
        try:
            df_copy = df.copy()
            df_copy['timestamp'] = pd.to_datetime(df_copy['timestamp'])
            df_copy['hour'] = df_copy['timestamp'].dt.floor('h')
            hourly_counts = df_copy[df_copy['violation_type'] == 'DETECTED'].groupby('hour').size()
            
            trend = []
            for hour, count in hourly_counts.items():
                trend.append({
                    'hour': hour.strftime('%H:%M'),
                    'timestamp': hour.isoformat(),
                    'violations': int(count)
                })
            
            return trend[-24:]  # Last 24 buckets
        except Exception as e:
            logger.warning(f"Trend error: {e}")
            return []

    def _get_recent_violations(self, df, n=10):
        try:
            recent = df.tail(n).copy()
            recent = recent.sort_values('timestamp', ascending=False)
            out = []
            for _, row in recent.iterrows():
                try:
                    items = json.loads(row['missing_items']) if isinstance(row['missing_items'], str) else row['missing_items']
                except:
                    items = []
                out.append({
                    'timestamp': str(row['timestamp']),
                    'person_id': str(row['person_id']),
                    'missing_items': items,
                    'violation_type': str(row['violation_type']),
                    'duration': float(row['duration']) if pd.notna(row['duration']) else None
                })
            return out
        except:
            return []
    
    def _get_avg_resolution_time(self, df) -> float:
        """Get average violation resolution time in seconds"""
        try:
            resolved_df = df[df['violation_type'] == 'RESOLVED']
            if resolved_df.empty:
                return 0
            # Filter numeric duration
            durations = pd.to_numeric(resolved_df['duration'], errors='coerce').dropna()
            return float(durations.mean()) if not durations.empty else 0
        except:
            return 0

    def get_recent_violations_df(self, limit=50):
        """Return DataFrame of recent violations for template"""
        if not HAS_PANDAS:
            # Return simple list-like object with .empty and iteration support for template fallback
            try:
                with open(self.violation_log_path, encoding='utf-8') as f:
                    reader = list(csv.DictReader(f))
                # Mimic DataFrame minimal API for template: provide .empty, .iterrows
                class FakeDF(list):
                    empty = len(reader)==0
                    def iterrows(self):
                        for idx, row in enumerate(reader[-limit:][::-1]):
                            yield idx, row
                fake = FakeDF(reader[-limit:][::-1])
                fake.empty = len(fake)==0
                return fake
            except Exception as e:
                logger.error(f"Failed to load recent violations (no pandas): {e}")
                class EmptyDF(list):
                    empty = True
                    def iterrows(self): return iter([])
                return EmptyDF()
        try:
            df = pd.read_csv(self.violation_log_path)
            if df.empty:
                return df
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df.sort_values('timestamp', ascending=False).head(limit)
        except Exception as e:
            logger.error(f"Failed to load recent violations: {e}")
            return pd.DataFrame()


# Global singleton for reuse across requests
_tracker_instance = None

def get_tracker(log_dir: str = None) -> ViolationTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = ViolationTracker(log_dir=log_dir)
    return _tracker_instance
