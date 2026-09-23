"""
PPE Configuration - Django port of original Streamlit config
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

@dataclass
class PPEConfig:
    # Model configuration
    MODEL_PATH: str = "ml_models/ppe_yolov10n.pt"
    # Fallback model name for ultralytics auto-download
    FALLBACK_MODEL: str = "yolov10n.pt"
    CONFIDENCE_THRESHOLD: float = 0.6
    IOU_THRESHOLD: float = 0.5
    IMG_SIZE: int = 640
    
    # PPE classes - custom PPE model expects these; COCO fallback maps differently
    CLASS_NAMES: List[str] = field(default_factory=lambda: ['helmet', 'safety_vest', 'gloves', 'industrial_shoes', 'person'])
    REQUIRED_PPE: List[str] = field(default_factory=lambda: ['helmet', 'safety_vest', 'gloves', 'industrial_shoes'])
    
    # Violation tracking
    VIOLATION_BUFFER: int = 10  # frames
    MIN_VIOLATION_DURATION: float = 2.0  # seconds
    VIOLATION_CONSISTENCY_FRAMES: int = 3  # consistent frames before flagging
    
    # UI settings
    DISPLAY_WIDTH: int = 1280
    DISPLAY_HEIGHT: int = 720
    FPS_UPDATE_INTERVAL: int = 30
    
    # Colors (BGR for OpenCV)
    COLOR_PALETTE: Dict[str, Tuple[int, int, int]] = field(default=None)
    
    def __post_init__(self):
        if self.COLOR_PALETTE is None:
            self.COLOR_PALETTE = {
                'helmet': (0, 255, 0),        # Green
                'safety_vest': (255, 255, 0), # Yellow
                'gloves': (0, 255, 255),      # Cyan
                'industrial_shoes': (255, 0, 255), # Magenta
                'person': (255, 165, 0),      # Orange
                'violation': (0, 0, 255),     # Red (BGR)
                'compliant': (0, 255, 0)      # Green
            }

    @classmethod
    def from_request(cls, request_data: dict):
        """Create config override from request parameters (sliders)"""
        cfg = cls()
        if 'confidence' in request_data:
            try:
                cfg.CONFIDENCE_THRESHOLD = float(request_data['confidence'])
            except: pass
        if 'iou' in request_data:
            try:
                cfg.IOU_THRESHOLD = float(request_data['iou'])
            except: pass
        return cfg

@dataclass
class UIConfig:
    # Theme colors
    PRIMARY_COLOR: str = "#1E88E5"
    SECONDARY_COLOR: str = "#FFC107"
    SUCCESS_COLOR: str = "#4CAF50"
    WARNING_COLOR: str = "#FF9800"
    DANGER_COLOR: str = "#F44336"
    DARK_BG: str = "#0f172a"
    
    # Layout
    SIDEBAR_WIDTH: int = 280
    MAIN_PADDING: int = 2
