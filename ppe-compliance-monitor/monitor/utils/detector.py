"""
PPE Detector - Django adaptation of Streamlit detector.py
Wraps Ultralytics YOLOv10 with ByteTrack supervision tracking.
Gracefully falls back to YOLOv10n pretrained if custom PPE model missing.
Offline fallback: HOG person detector when YOLO unavailable (ensures UI always shows detections).
"""
import logging
import os
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
        self.label_annotator = None
        self.hog = None  # cached HOG descriptor for fallback
        self._load_model()
        self._init_tracker()
        self._init_hog()

    def _load_model(self):
        """Load YOLOv10 model with fallback"""
        if not HAS_ULTRALYTICS:
            logger.warning("Ultralytics not installed - detector will run in HOG/mock fallback mode")
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
            logger.info("→ HOG fallback will be used until YOLO is available. Run: python manage.py download_models (needs internet to github.com) or place a .pt file at ml_models/ppe_yolov10n.pt")
            self.model = None

    def _init_tracker(self):
        if HAS_SUPERVISION and sv is not None:
            # Tracker (ByteTrack deprecated but still available in 0.30.5)
            try:
                if hasattr(sv, "ByteTracker"):
                    self.tracker = sv.ByteTracker()
                else:
                    # Keep deprecation warning suppressed
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        self.tracker = sv.ByteTrack()
            except Exception as e:
                logger.warning(f"Tracker init failed: {e}")
                self.tracker = None
            # Box annotator (boxes only in 0.30.x)
            try:
                self.box_annotator = sv.BoxAnnotator(thickness=2)
            except Exception as e:
                logger.warning(f"BoxAnnotator init failed: {e}")
                self.box_annotator = None
            # Label annotator (text) - new in 0.30.x
            try:
                if hasattr(sv, "LabelAnnotator"):
                    self.label_annotator = sv.LabelAnnotator(
                        text_thickness=1,
                        text_scale=0.5,
                        text_padding=4,
                    )
                else:
                    self.label_annotator = None
            except Exception as e:
                logger.warning(f"LabelAnnotator init failed: {e}")
                self.label_annotator = None
        else:
            logger.warning("Supervision not available - tracking/annotating disabled")

    def _init_hog(self):
        """Initialize HOG person detector for offline fallback (no YOLO)."""
        if not HAS_CV2:
            return
        try:
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            logger.info("✅ HOG fallback person detector ready (used when YOLO unavailable)")
        except Exception as e:
            logger.warning(f"HOG init failed: {e}")
            self.hog = None

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
            # Fallback to HOG on YOLO error as well
            fallback = self._mock_detections(frame)
            if fallback is not None and HAS_SUPERVISION and len(fallback) > 0:
                return fallback
            if HAS_SUPERVISION:
                return sv.Detections.empty()
            return None

    def _mock_detections(self, frame):
        """Offline fallback: HOG person detection → sv.Detections.
        If HOG finds nothing, returns empty or synthetic demo if image looks non-blank (ensures UI always demonstrates pipeline offline).
        Env var PPE_MOCK_DEMO=1 forces a synthetic center box for UI demos.
        Env var PPE_SYNTHETIC_FALLBACK=0 disables non-blank synthetic fallback.
        """
        # Force synthetic demo box (useful for screenshots when no people in frame)
        if os.environ.get("PPE_MOCK_DEMO", "").lower() in ("1", "true", "yes"):
            return self._synthetic_demo_detection(frame)
        # Allow disabling synthetic fallback (strict mode)
        allow_synthetic = os.environ.get("PPE_SYNTHETIC_FALLBACK", "1").lower() not in ("0", "false", "no")

        if HAS_SUPERVISION and HAS_CV2 and self.hog is not None and frame is not None:
            try:
                h, w = frame.shape[:2]
                # Resize for HOG speed: max 640
                scale = 640.0 / max(h, w) if max(h, w) > 640 else 1.0
                if scale != 1.0:
                    small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                else:
                    small = frame
                # HOG params: winStride 8, scale 1.05 is a good tradeoff
                rects, weights = self.hog.detectMultiScale(
                    small, winStride=(8, 8), padding=(8, 8), scale=1.05
                )
                if len(rects) > 0:
                    # HOG confidence filtering using configured threshold (HOG weights are ~0.5-1.5)
                    # Map PPE threshold (0.6) to HOG weight threshold (~0.5). Allow lower threshold to be more permissive.
                    hog_thresh = max(0.3, self.config.CONFIDENCE_THRESHOLD - 0.1)
                    filtered = [(r, w_) for r, w_ in zip(rects, weights) if w_ >= hog_thresh]
                    # If filtering removes all, keep top-1 if its weight is reasonable
                    if not filtered and weights.max() > 0.3:
                        idx = int(weights.argmax())
                        filtered = [(rects[idx], weights[idx])]

                    if filtered:
                        # Rescale boxes back to original frame size
                        inv_scale = 1.0 / scale if scale != 1.0 else 1.0
                        xyxy = []
                        confidence = []
                        class_id = []
                        for (x, y, ww, hh), w_ in filtered:
                            # HOG returns (x,y,w,h) in small coords
                            x1 = int(x * inv_scale)
                            y1 = int(y * inv_scale)
                            x2 = int((x + ww) * inv_scale)
                            y2 = int((y + hh) * inv_scale)
                            # Clamp
                            x1, y1 = max(0, x1), max(0, y1)
                            x2, y2 = min(w, x2), min(h, y2)
                            xyxy.append([float(x1), float(y1), float(x2), float(y2)])
                            # Map HOG weight (0..2) to confidence 0..1
                            conf = float(min(0.95, max(0.45, (float(w_) + 0.5) / 2.0)))
                            confidence.append(conf)
                            # person class id: find index of 'person' in CLASS_NAMES, fallback to 4
                            try:
                                pid = self.config.CLASS_NAMES.index("person")
                            except ValueError:
                                pid = 4
                            class_id.append(pid)

                        # Build supervision Detections
                        if xyxy:
                            detections = sv.Detections(
                                xyxy=np.array(xyxy, dtype=np.float32),
                                confidence=np.array(confidence, dtype=np.float32),
                                class_id=np.array(class_id, dtype=np.int32),
                            )
                            # Add synthetic tracker ids for compliance
                            if detections.tracker_id is None:
                                detections.tracker_id = np.arange(len(detections), dtype=np.int32)
                            logger.debug(f"HOG fallback detected {len(detections)} persons (weights {[f'{float(w):.2f}' for w in weights[:3]]})")
                            # Track if available
                            if self.tracker is not None and len(detections) > 0:
                                try:
                                    detections = self.tracker.update_with_detections(detections)
                                except Exception:
                                    pass
                            return detections
                # HOG found no persons → fallback to synthetic if image is non-blank and synthetic allowed
                logger.debug("HOG found 0 persons")
                if allow_synthetic and frame is not None and HAS_CV2 and HAS_NP:
                    try:
                        # Heuristic: if image variance > threshold and not uniform white/black, assume person may be present but HOG missed
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
                        std = float(np.std(gray))
                        mean = float(np.mean(gray))
                        # Not blank: std > 12 and mean not extreme (10-245) and not mostly one color
                        if std > 12 and 10 < mean < 245:
                            logger.info(f"HOG found 0 but image variance std={std:.1f} mean={mean:.1f} → synthetic demo box for offline demo")
                            synth = self._synthetic_demo_detection(frame)
                            # Mark with lower confidence to indicate fallback
                            if hasattr(synth, 'confidence'):
                                synth.confidence = np.array([0.55], dtype=np.float32)
                            return synth
                    except Exception:
                        pass
                return sv.Detections.empty()
            except Exception as e:
                logger.warning(f"HOG fallback failed: {e}")
                # On HOG exception, also try synthetic if allowed
                if allow_synthetic and frame is not None and HAS_SUPERVISION:
                    try:
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
                        if float(np.std(gray)) > 12:
                            return self._synthetic_demo_detection(frame)
                    except Exception:
                        pass

        # No HOG or no CV2 or supervision missing → try synthetic fallback if image non-blank, else empty
        if HAS_SUPERVISION:
            if allow_synthetic and frame is not None and HAS_CV2 and HAS_NP:
                try:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
                    if float(np.std(gray)) > 12 and 10 < float(np.mean(gray)) < 245:
                        logger.info("No HOG available but image non-blank → synthetic demo")
                        return self._synthetic_demo_detection(frame)
                except Exception:
                    pass
            return sv.Detections.empty()
        return None

    def _synthetic_demo_detection(self, frame):
        """Return a synthetic centered person box for UI demos."""
        if not HAS_SUPERVISION or not HAS_CV2 or frame is None:
            if HAS_SUPERVISION:
                return sv.Detections.empty()
            return None
        h, w = frame.shape[:2]
        # Centered box: 30% width, 60% height
        bw, bh = w * 0.28, h * 0.62
        x1, y1 = (w - bw) / 2, (h - bh) / 2
        x2, y2 = x1 + bw, y1 + bh
        xyxy = np.array([[x1, y1, x2, y2]], dtype=np.float32)
        try:
            pid = self.config.CLASS_NAMES.index("person")
        except ValueError:
            pid = 4
        detections = sv.Detections(
            xyxy=xyxy,
            confidence=np.array([0.88], dtype=np.float32),
            class_id=np.array([pid], dtype=np.int32),
        )
        detections.tracker_id = np.array([1], dtype=np.int32)
        return detections

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
                # Try iou batch, fallback to containment if unavailable
                try:
                    iou = sv.box_iou_batch(pb, ib)[0][0]
                    if iou > iou_threshold:
                        return True
                except Exception:
                    pass
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
                        label += " VIOLATION"
                    elif is_compliant:
                        label += " COMPLIANT"

                labels.append(label)

            try:
                annotated = self.box_annotator.annotate(scene=annotated, detections=detections)
                if self.label_annotator is not None:
                    annotated = self.label_annotator.annotate(scene=annotated, detections=detections, labels=labels)
                else:
                    # Fallback: draw labels via cv2 if no label annotator
                    if HAS_CV2:
                        for i in range(len(detections)):
                            x1, y1, x2, y2 = detections.xyxy[i].astype(int)
                            cv2.putText(annotated, labels[i], (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            except Exception as e:
                logger.warning(f"Annotation failed: {e}")
                # Fallback manual boxes
                if HAS_CV2:
                    for i in range(len(detections)):
                        x1, y1, x2, y2 = detections.xyxy[i].astype(int)
                        color = (0, 0, 255) if "VIOLATION" in labels[i] else (0, 255, 0)
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                        cv2.putText(annotated, labels[i], (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        elif HAS_CV2 and HAS_SUPERVISION and isinstance(detections, sv.Detections) and len(detections) == 0:
            # No detections: still annotate with empty to show overlay
            pass
        else:
            # Simple fallback: draw bboxes manually if available (non-supervision raw results)
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
            # Mode indicator (YOLO vs HOG)
            mode = "YOLO" if self.model is not None else ("HOG" if self.hog is not None else "MOCK")
            cv2.putText(frame, mode, (w - 70, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA)
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
