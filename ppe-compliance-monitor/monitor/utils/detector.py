"""
PPE Detector - Django adaptation of Streamlit detector.py
Wraps Ultralytics YOLOv10 with ByteTrack supervision tracking.
Gracefully falls back to YOLOv10n pretrained if custom PPE model missing.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional

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

from .config import PPEConfig

logger = logging.getLogger(__name__)

try:
    from ultralytics import YOLO
    # YOLOv10 is accessed via YOLO('yolov10n.pt') in latest ultralytics
    HAS_ULTRALYTICS = True
except ImportError:
    HAS_ULTRALYTICS = False
    YOLO = None

try:
    import supervision as sv
    HAS_SUPERVISION = True
except ImportError:
    HAS_SUPERVISION = False
    sv = None


class PPEDetector:
    def __init__(self, config: PPEConfig = None):
        self.config = config or PPEConfig()
        self.model = None
        self.tracker = None
        self.box_annotator = None
        self._load_model()
        self._init_tracker()

    def _load_model(self):
        """Load YOLOv10 model with fallback"""
        if not HAS_ULTRALYTICS:
            logger.warning("Ultralytics not installed - detector will run in mock mode")
            return

        model_path = Path(self.config.MODEL_PATH)
        # Try custom PPE model first
        try:
            if model_path.exists():
                self.model = YOLO(str(model_path))
                logger.info(f"✅ Custom PPE model loaded from {model_path}")
                return
        except Exception as e:
            logger.warning(f"Failed to load custom model {model_path}: {e}")

        # Fallback to pretrained YOLOv10n (will auto-download)
        try:
            fallback = self.config.FALLBACK_MODEL
            logger.info(f"🔄 Loading fallback model {fallback}...")
            self.model = YOLO(fallback)
            logger.info("✅ Fallback YOLO model loaded")
        except Exception as e:
            logger.error(f"❌ Failed to load fallback model: {e}")
            self.model = None

    def _init_tracker(self):
        if HAS_SUPERVISION and sv is not None:
            try:
                self.tracker = sv.ByteTrack()
                self.box_annotator = sv.BoxAnnotator(
                    thickness=2,
                    text_thickness=1,
                    text_scale=0.5
                )
            except Exception as e:
                logger.warning(f"Tracker init failed: {e}")
                self.tracker = None
        else:
            logger.warning("Supervision not available - tracking disabled")

    def detect(self, frame):
        """Perform PPE detection on frame. Returns sv.Detections or mock."""
        if self.model is None:
            return self._mock_detections(frame)

        try:
            results = self.model(
                frame,
                conf=self.config.CONFIDENCE_THRESHOLD,
                iou=self.config.IOU_THRESHOLD,
                imgsz=self.config.IMG_SIZE,
                verbose=False
            )[0]

            if HAS_SUPERVISION:
                detections = sv.Detections.from_ultralytics(results)
                if self.tracker is not None and len(detections) > 0:
                    detections = self.tracker.update_with_detections(detections)
                return detections
            else:
                # Without supervision, return raw ultralytics boxes
                return results

        except Exception as e:
            logger.error(f"Detection error: {e}")
            if HAS_SUPERVISION:
                return sv.Detections.empty()
            return None

    def _mock_detections(self, frame):
        """Return empty detections when model unavailable (allows UI testing)"""
        if HAS_SUPERVISION:
            return sv.Detections.empty()
        return None

    def analyze_compliance(self, detections) -> Dict:
        """Analyze PPE compliance for detected persons"""
        compliance_data = {
            'violations': [],
            'compliant': [],
            'missing_items': {},
            'person_count': 0,
            'total_detections': 0
        }

        if detections is None:
            return compliance_data

        # Handle supervision Detections
        if HAS_SUPERVISION and isinstance(detections, sv.Detections):
            if len(detections) == 0:
                return compliance_data

            compliance_data['total_detections'] = len(detections)

            # Extract person and PPE detections
            person_detections = []
            ppe_detections = {item: [] for item in self.config.REQUIRED_PPE}

            for i in range(len(detections)):
                class_id = int(detections.class_id[i])
                tracker_id = int(detections.tracker_id[i]) if detections.tracker_id is not None else i

                # Map class_id to name - handle both custom PPE and COCO fallback
                if class_id < len(self.config.CLASS_NAMES):
                    class_name = self.config.CLASS_NAMES[class_id]
                else:
                    # COCO class 0 is person; others we treat as generic
                    # For COCO fallback, only person is reliable
                    if class_id == 0:
                        class_name = 'person'
                    else:
                        continue

                if class_name == 'person':
                    person_detections.append({
                        'detection_idx': i,
                        'tracker_id': tracker_id,
                        'bbox': detections.xyxy[i]
                    })
                elif class_name in self.config.REQUIRED_PPE:
                    ppe_detections[class_name].append({
                        'detection_idx': i,
                        'tracker_id': tracker_id,
                        'bbox': detections.xyxy[i]
                    })

            compliance_data['person_count'] = len(person_detections)

            # Check compliance for each person
            for person in person_detections:
                person_bbox = person['bbox']
                person_id = person['tracker_id']

                missing_items = self.config.REQUIRED_PPE.copy()

                for ppe_type, ppe_list in ppe_detections.items():
                    for ppe in ppe_list:
                        if self._is_item_associated(person_bbox, ppe['bbox']):
                            if ppe_type in missing_items:
                                missing_items.remove(ppe_type)

                if missing_items:
                    compliance_data['violations'].append({
                        'person_id': person_id,
                        'missing_items': missing_items,
                        'bbox': person_bbox.tolist() if hasattr(person_bbox, 'tolist') else list(person_bbox)
                    })
                    compliance_data['missing_items'][str(person_id)] = missing_items
                else:
                    compliance_data['compliant'].append({
                        'person_id': person_id,
                        'bbox': person_bbox.tolist() if hasattr(person_bbox, 'tolist') else list(person_bbox)
                    })
        else:
            # Fallback without supervision - minimal compliance check
            compliance_data['person_count'] = 0

        return compliance_data

    def _is_item_associated(self, person_bbox, item_bbox, iou_threshold: float = 0.15) -> bool:
        """Check if PPE item is associated with a person using IoU or containment"""
        try:
            if HAS_SUPERVISION:
                pb = np.array(person_bbox).reshape(1, -1)
                ib = np.array(item_bbox).reshape(1, -1)
                iou = sv.box_iou_batch(pb, ib)[0][0]
                if iou > iou_threshold:
                    return True
                # Fallback: check center containment (PPE inside person bbox expanded)
                ix1, iy1, ix2, iy2 = ib[0]
                px1, py1, px2, py2 = pb[0]
                cx, cy = (ix1+ix2)/2, (iy1+iy2)/2
                # Loose containment with 10% expansion
                expand = 0.1
                w, h = px2-px1, py2-py1
                if (px1 - w*expand) <= cx <= (px2 + w*expand) and (py1 - h*expand) <= cy <= (py2 + h*expand):
                    return True
                return False
            else:
                return False
        except Exception:
            return False

    def annotate_frame(self, frame, detections, compliance_data: Dict):
        """Annotate frame with detection results and compliance status"""
        annotated = frame.copy()

        # Draw detections if supervision available
        if HAS_SUPERVISION and isinstance(detections, sv.Detections) and len(detections) > 0 and self.box_annotator:
            labels = []
            for i in range(len(detections)):
                class_id = int(detections.class_id[i])
                tracker_id = int(detections.tracker_id[i]) if detections.tracker_id is not None else i
                conf = float(detections.confidence[i]) if detections.confidence is not None else 0.0

                if class_id < len(self.config.CLASS_NAMES):
                    class_name = self.config.CLASS_NAMES[class_id]
                else:
                    class_name = f"class_{class_id}" if class_id != 0 else "person"

                label = f"{class_name} #{tracker_id} {conf:.2f}"

                # Compliance suffix for persons
                if class_name == 'person':
                    # Find if this person is in violations
                    is_violation = any(v['person_id'] == tracker_id for v in compliance_data.get('violations', []))
                    is_compliant = any(c['person_id'] == tracker_id for c in compliance_data.get('compliant', []))
                    if is_violation:
                        label += " ⚠️ VIOLATION"
                    elif is_compliant:
                        label += " ✅ COMPLIANT"

                labels.append(label)

            try:
                annotated = self.box_annotator.annotate(
                    scene=annotated,
                    detections=detections,
                    labels=labels
                )
            except Exception as e:
                logger.warning(f"Annotation failed: {e}")
        else:
            # Simple fallback: draw bboxes manually if available
            pass

        # Add compliance summary overlay
        annotated = self._add_compliance_overlay(annotated, compliance_data)
        return annotated

    def _add_compliance_overlay(self, frame, compliance_data: Dict):
        """Add compliance status overlay to frame"""
        if not HAS_CV2 or not HAS_NP:
            return frame
        try:
            h, w = frame.shape[:2]
            overlay = frame.copy()
            cv2.rectangle(overlay, (10, 10), (340, 135), (0, 0, 0), -1)
            frame = cv2.addWeighted(overlay, 0.65, frame, 0.35, 0)

            status_lines = [
                (f"Persons: {compliance_data.get('person_count', 0)}", (255, 255, 255)),
                (f"Compliant: {len(compliance_data.get('compliant', []))}", (0, 255, 0)),
                (f"Violations: {len(compliance_data.get('violations', []))}", (0, 0, 255) if compliance_data.get('violations') else (200, 200, 200)),
            ]
            for i, (text, color) in enumerate(status_lines):
                y = 38 + i * 32
                cv2.putText(frame, text, (22, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2, cv2.LINE_AA)

            from datetime import datetime
            ts = datetime.now().strftime("%H:%M:%S")
            cv2.putText(frame, ts, (w - 110, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        except Exception as e:
            logger.warning(f"Overlay failed: {e}")
        return frame

# Singleton holder for efficiency
_detector_instance = None

def get_detector(config: PPEConfig = None) -> PPEDetector:
    global _detector_instance
    if _detector_instance is None or config is not None:
        # If config overridden, create new instance; else reuse
        if config is not None:
            return PPEDetector(config)
        _detector_instance = PPEDetector()
    return _detector_instance
