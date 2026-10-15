"""Local pretrained inference; model download is a separate explicit setup step."""
from pathlib import Path
import os
import threading

import cv2
import numpy as np

DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
DEPTH_REVISION = "8078d68a9c75a972131914f6afd0c1723be0da7f"
DETECTOR_FILE = "ssdlite320_mobilenet_v3_large_coco-a79551df.pth"


class LocalModels:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.depth_model = self.detector = self.processor = None
        self.device = "cpu"  # Baseline works on Windows without a CUDA toolchain.
        self.categories = []
        self.depth_size = 392

    def availability(self):
        return {"depth_installed": (self.root / "depth" / "model.safetensors").is_file(),
                "detector_installed": (self.root / DETECTOR_FILE).is_file(),
                "depth_loaded": self.depth_model is not None, "detector_loaded": self.detector is not None,
                "depth_model": DEPTH_MODEL, "device": self.device,
                "depth_scope": "indoor_estimate_not_a_measured_range", "inference": "local_only",
                "depth_input_size": self.depth_size}

    def load(self, need_depth=True, need_detection=True):
        import torch
        torch.set_num_threads(max(1, min(4, (os.cpu_count() or 2) // 2)))
        with self.lock:
            if need_depth and self.depth_model is None:
                folder = self.root / "depth"
                if not (folder / "model.safetensors").is_file():
                    raise RuntimeError("Depth model missing. Run setup_windows.bat or tools/prepare_assets.py --models")
                from transformers import AutoImageProcessor, AutoModelForDepthEstimation
                self.processor = AutoImageProcessor.from_pretrained(folder, local_files_only=True, use_fast=False)
                self.depth_model = AutoModelForDepthEstimation.from_pretrained(folder, local_files_only=True,
                    use_safetensors=True).to(self.device).eval()
            if need_detection and self.detector is None:
                path = self.root / DETECTOR_FILE
                if not path.is_file():
                    raise RuntimeError("Object detector missing. Run tools/prepare_assets.py --models")
                from torchvision.models.detection import ssdlite320_mobilenet_v3_large, SSDLite320_MobileNet_V3_Large_Weights
                self.detector = ssdlite320_mobilenet_v3_large(weights=None, weights_backbone=None)
                self.detector.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
                self.detector.to(self.device).eval()
                self.categories = SSDLite320_MobileNet_V3_Large_Weights.COCO_V1.meta["categories"]

    def depth(self, rgb):
        import torch
        if self.depth_model is None:
            self.load(True, False)
        with self.lock, torch.inference_mode():
            # The transformer grid trades detail for CPU latency. Output remains
            # predicted metric depth, never the colorized 8-bit visualization.
            inputs = self.processor(images=rgb, return_tensors="pt",
                                    size={"height": self.depth_size, "width": self.depth_size})
            predicted = self.depth_model(**{k: v.to(self.device) for k, v in inputs.items()}).predicted_depth
            output = torch.nn.functional.interpolate(predicted[:, None], size=rgb.shape[:2],
                                                     mode="bilinear", align_corners=False)[0, 0]
            depth = output.cpu().numpy().astype(np.float32)
        depth[~np.isfinite(depth) | (depth <= 0) | (depth > 20)] = 0
        return depth

    def detect(self, rgb, threshold=.55):
        import torch
        if self.detector is None:
            self.load(False, True)
        with self.lock, torch.inference_mode():
            image = torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1))).float().to(self.device) / 255
            output = self.detector([image])[0]
            boxes, labels, scores = [output[name].cpu().numpy() for name in ("boxes", "labels", "scores")]
        results = []
        for box, label, score in zip(boxes, labels, scores):
            if score < threshold or len(results) >= 25:
                continue
            name = self.categories[int(label)]
            results.append({"label": name, "label_id": int(label), "confidence": round(float(score), 4),
                            "box": [round(float(v), 2) for v in box],
                            "potentially_dynamic_class": name in {"person", "car", "truck", "bus", "motorcycle", "bicycle", "dog", "cat"}})
        return results


def static_mask(shape, detections):
    mask = np.ones(shape, bool)
    for detection in detections:
        if detection["potentially_dynamic_class"]:
            x1, y1, x2, y2 = detection["box"]
            # Mask people/vehicles conservatively; this is NOT a motion assertion.
            mask[max(0, int(y1) - 6):min(shape[0], int(y2) + 7),
                 max(0, int(x1) - 6):min(shape[1], int(x2) + 7)] = False
    return mask


def depth_preview(depth):
    valid = np.isfinite(depth) & (depth > 0)
    image = np.zeros(depth.shape, np.uint8)
    if valid.any():
        lo, hi = np.percentile(depth[valid], (2, 98))
        image[valid] = np.clip((depth[valid] - lo) / max(hi - lo, .01) * 255, 0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(255 - image, cv2.COLORMAP_TURBO)
    colored[~valid] = 0
    return cv2.imencode(".jpg", colored, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
