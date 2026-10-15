"""Real image sources: public recorded RGB-D, video, camera or submitted JPEG."""
import json
from pathlib import Path
import time

import cv2
import numpy as np

from .geometry import Intrinsics


def decode_image(raw):
    if not raw or len(raw) > 5000000:
        raise ValueError("Image must be between 1 byte and 5 MB")
    # Validate dimensions before OpenCV allocates the full decoded image.
    from PIL import Image
    import io
    with Image.open(io.BytesIO(raw)) as info:
        if info.width * info.height > 12000000 or min(info.size) < 32:
            raise ValueError("Image dimensions outside supported range")
    bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Image decode failed")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def bounded_rgb(rgb, maximum=640):
    height, width = rgb.shape[:2]
    ratio = min(1., maximum / max(height, width))
    if ratio < 1:
        rgb = cv2.resize(rgb, (round(width * ratio), round(height * ratio)), interpolation=cv2.INTER_AREA)
    return rgb


class RecordingSource:
    def __init__(self, folder, rgb_only=False):
        self.folder = Path(folder).resolve()
        manifest = self.folder / "manifest.json"
        if not manifest.is_file():
            raise ValueError("Test recording missing. Run tools/prepare_assets.py --sample")
        self.manifest = json.loads(manifest.read_text(encoding="utf-8"))
        self.frames = self.manifest["frames"]
        self.intrinsics = Intrinsics.from_dict(self.manifest["intrinsics"])
        self.index = 0
        self.rgb_only = rgb_only
        self.depth_kind = "model_estimated_metric" if rgb_only else "sensor_metric"

    def read(self):
        if self.index >= len(self.frames): return None
        frame = self.frames[self.index]; self.index += 1
        def location(key):
            path = (self.folder / frame[key]).resolve()
            if not path.is_relative_to(self.folder): raise ValueError("Invalid recording path")
            return path
        bgr = cv2.imread(str(location("rgb")))
        if bgr is None: raise ValueError("Recorded RGB image missing")
        depth = None
        if not self.rgb_only:
            image = cv2.imread(str(location("depth")), cv2.IMREAD_UNCHANGED)
            if image is None or image.dtype != np.uint16: raise ValueError("Registered 16-bit depth image missing")
            depth = image.astype(np.float32) / float(self.manifest["depth_divisor"])
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), depth, self.intrinsics, float(frame["timestamp"])

    def close(self): pass


class VideoSource:
    def __init__(self, source, intrinsics=None, is_camera=False):
        self.capture = cv2.VideoCapture(source, cv2.CAP_DSHOW if is_camera else cv2.CAP_ANY)
        if not self.capture.isOpened():
            self.capture.release()
            raise ValueError("Camera/video could not be opened")
        self.camera = is_camera
        self.intrinsics = intrinsics
        self.fps = self.capture.get(cv2.CAP_PROP_FPS)
        if not np.isfinite(self.fps) or not 1 <= self.fps <= 240: self.fps = 30.
        self.index = 0
        self.depth_kind = "model_estimated_metric"

    def read(self):
        ok, image = self.capture.read()
        if not ok: return None
        timestamp = time.time() if self.camera else self.index / self.fps
        self.index += 1
        # Sequential processing preserves actual source time. It is not promised
        # to play back in real time on a slow CPU.
        rgb = bounded_rgb(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        h, w = rgb.shape[:2]
        k = self.intrinsics.resized(w, h) if self.intrinsics else Intrinsics.assumed(w, h)
        return rgb, None, k, timestamp

    def close(self): self.capture.release()
