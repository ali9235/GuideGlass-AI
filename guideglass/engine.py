"""One bounded reconstruction worker shared by Windows and phone clients."""
import json
from pathlib import Path
import queue
import re
import struct
import threading
import time
import uuid

import cv2
import numpy as np

from .geometry import Intrinsics, PoseTracker, VoxelMap, backproject, transform_points, detection_locations
from .models import LocalModels, static_mask, depth_preview
from .sources import RecordingSource, VideoSource, bounded_rgb, decode_image
from .storage import MapStore


class SpatialEngine:
    def __init__(self, root, frame_fetcher=None, models=None):
        self.root = Path(root)
        self.models = models or LocalModels(self.root / "models")
        self.maps = MapStore(self.root / ".data" / "maps")
        self.frame_fetcher = frame_fetcher
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        self.inbox = queue.Queue(maxsize=1)
        self.sequence = 0
        self.cloud_cache = None
        self._reset("idle")

    def _reset(self, phase, voxel_size=.035):
        self.map = VoxelMap(voxel_size)
        self.tracker = PoseTracker()
        self.trajectory = []
        self.frame_jpeg = self.depth_jpeg = None
        self.session_id = uuid.uuid4().hex
        self.last_timestamp = None
        self.sequence += 1
        self.cloud_cache = None
        self.info = {"phase": phase, "source": None, "depth_kind": None, "intrinsics": None,
            "frames_processed": 0, "frames_fused": 0, "frames_rejected": 0, "frames_dropped": 0,
            "tracking": {"state": "waiting"}, "detections": [], "pose": None,
            "processing_fps": None, "last_frame_at": None, "error": None,
            "global_loop_optimization": False, "map_mode": "live", "motion_analysis": "not_implemented",
            "depth_uncertainty": "No calibrated per-pixel uncertainty available", "detector_enabled": False}

    def start(self, options):
        source_name = options.get("source", "sample")
        if source_name not in {"sample", "sample_rgb", "video", "webcam", "browser", "esp32"}:
            raise ValueError("Unsupported source")
        intrinsics = Intrinsics.from_dict(options["intrinsics"]) if options.get("intrinsics") else None
        voxel = float(options.get("voxel_size", .035))
        VoxelMap(voxel)  # Validate before changing the active session.
        video_path = None
        if source_name == "video":
            video_id = str(options.get("video_id", ""))
            if not re.fullmatch(r"[0-9a-f]{32}", video_id): raise ValueError("Upload a video first")
            video_path = self.root / ".data" / "uploads" / (video_id + ".mp4")
            if not video_path.is_file(): raise ValueError("Uploaded video is missing")
        if source_name.startswith("sample") and not (self.root / ".data/samples/tum_xyz/manifest.json").is_file():
            raise ValueError("Run tools/prepare_assets.py --sample to install the real test recording")
        camera_index = int(options.get("camera_index", 0))
        if not 0 <= camera_index <= 4: raise ValueError("Camera index must be 0–4")
        detection = options.get("detect", True)
        if not isinstance(detection, bool): raise ValueError("Detection option must be boolean")
        depth_size = int(options.get("depth_size", 392))
        if depth_size not in {280, 392, 518}: raise ValueError("Depth resolution must be 280, 392 or 518")
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError("Stop the current scan and wait before starting a new one")
            self.stop_event = threading.Event()
            self.inbox = queue.Queue(maxsize=1)
            self._reset("loading_models", voxel)
            self.models.depth_size = depth_size
            self.info.update(source=source_name, detector_enabled=detection,
                depth_kind="sensor_metric" if source_name == "sample" else "model_estimated_metric",
                depth_input_size=depth_size)
            self.worker = threading.Thread(target=self._run,
                args=(source_name, intrinsics, video_path, camera_index, detection), daemon=True, name="GuideGlass-spatial")
            self.worker.start()
            return self.state()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            if self.worker and self.worker.is_alive(): self.info["phase"] = "stopping"
        return self.state()

    def submit_frame(self, raw, session_id, timestamp):
        with self.lock:
            if session_id != self.session_id or self.info["source"] != "browser" or self.stop_event.is_set():
                raise ValueError("This browser camera session is no longer active")
            if not self.worker or not self.worker.is_alive(): raise ValueError("Start the browser camera scan first")
        if not np.isfinite(timestamp): raise ValueError("Invalid capture timestamp")
        rgb = bounded_rgb(decode_image(raw))
        try:
            self.inbox.put_nowait((rgb, timestamp))
        except queue.Full:
            try: self.inbox.get_nowait()
            except queue.Empty: pass
            try: self.inbox.put_nowait((rgb, timestamp))
            except queue.Full: pass
            with self.lock: self.info["frames_dropped"] += 1

    def _run(self, source_name, intrinsics, video_path, camera_index, detect):
        source = None
        try:
            self.models.load(need_depth=source_name != "sample", need_detection=detect)
            if self.stop_event.is_set(): return
            if source_name in {"sample", "sample_rgb"}:
                source = RecordingSource(self.root / ".data/samples/tum_xyz", rgb_only=source_name == "sample_rgb")
            elif source_name in {"video", "webcam"}:
                source = VideoSource(camera_index if source_name == "webcam" else str(video_path), intrinsics,
                                     is_camera=source_name == "webcam")
            with self.lock: self.info["phase"] = "waiting_for_frame"
            while not self.stop_event.is_set():
                if source:
                    item = source.read()
                    if item is None:
                        with self.lock: self.info["phase"] = "completed"
                        break
                else:
                    if source_name == "browser":
                        try: rgb, timestamp = self.inbox.get(timeout=.4)
                        except queue.Empty: continue
                    else:
                        if not self.frame_fetcher: raise ValueError("ESP32 camera bridge is not configured")
                        rgb, timestamp = bounded_rgb(decode_image(self.frame_fetcher())), time.time()
                    height, width = rgb.shape[:2]
                    k = intrinsics.resized(width, height) if intrinsics else Intrinsics.assumed(width, height)
                    item = (rgb, None, k, timestamp)
                self.process_frame(*item, detect=detect)
                if source_name == "esp32": self.stop_event.wait(.05)
        except Exception as error:
            with self.lock:
                self.info.update(phase="error", error=f"{type(error).__name__}: {str(error)[:400]}")
        finally:
            if source: source.close()
            with self.lock:
                if self.stop_event.is_set() and self.info["phase"] != "error": self.info["phase"] = "stopped"

    def process_frame(self, rgb, depth, intrinsics, timestamp, detect=True):
        started = time.perf_counter()
        with self.lock:
            if self.last_timestamp is not None and timestamp <= self.last_timestamp:
                self.info["frames_dropped"] += 1
                return
            self.last_timestamp = timestamp
            self.info["phase"] = "analyzing"
        estimated = depth is None
        if estimated: depth = self.models.depth(rgb)
        depth = np.asarray(depth, dtype=np.float32)
        if depth.shape != rgb.shape[:2] or rgb.shape[:2] != (intrinsics.height, intrinsics.width):
            raise ValueError("RGB and registered depth dimensions do not match camera intrinsics")
        detections = self.models.detect(rgb) if detect else []
        mask = static_mask(depth.shape, detections)
        pose, tracking = self.tracker.update(rgb, depth, intrinsics, mask, timestamp, estimated=estimated)
        depth_kind = "model_estimated_metric" if estimated else "sensor_metric"
        objects = detection_locations(detections, depth, intrinsics, pose, depth_kind)
        frame_jpeg = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tobytes()
        depth_jpeg = depth_preview(depth)
        points = colors = None
        if pose is not None:
            points, colors = backproject(depth, rgb, intrinsics, stride=3, mask=mask)
            points = transform_points(points, pose)
        with self.lock:
            # Emergency stop while a neural model was running must not fuse its late result.
            if self.stop_event.is_set(): return
            if points is not None:
                self.map.fuse(points, colors)
                self.trajectory.append(pose.copy())
                self.trajectory = self.trajectory[-20000:]
                self.sequence += 1
                self.cloud_cache = None
                self.info["frames_fused"] += 1
            else:
                self.info["frames_rejected"] += 1
            self.frame_jpeg, self.depth_jpeg = frame_jpeg, depth_jpeg
            self.info["frames_processed"] += 1
            elapsed = time.perf_counter() - started
            self.info.update(phase="tracking" if pose is not None else "tracking_lost", tracking=tracking,
                intrinsics=intrinsics.json(), depth_kind=depth_kind, detections=objects,
                pose=pose.tolist() if pose is not None else None, last_frame_at=time.time(),
                capture_timestamp=timestamp, latency_ms=round(elapsed * 1000, 1), processing_fps=round(1 / max(elapsed, .001), 2),
                depth_valid_fraction=round(float(((depth > .15) & (depth < 12) & np.isfinite(depth)).mean()), 4),
                distance_unit="estimated_meters" if estimated else "sensor_meters")

    def state(self):
        with self.lock:
            # Clone structured data; callers must not mutate the worker state.
            result = json.loads(json.dumps(self.info, allow_nan=False))
            result.update(session_id=self.session_id, cloud_sequence=self.sequence, point_count=len(self.map.cells),
                display_point_limit=80000, map_capacity=self.map.max_points, capacity_reached=self.map.capacity_reached,
                running=bool(self.worker and self.worker.is_alive()), models=self.models.availability(),
                sample_available=(self.root / ".data/samples/tum_xyz/manifest.json").is_file(),
                web_assets_available=(self.root / "vendor/three.module.js").is_file(),
                trajectory=[pose[:3, 3].tolist() for pose in self.trajectory[-1500:]])
            return result

    def cloud(self, since=None):
        with self.lock:
            if since == self.sequence: return None
            if self.cloud_cache is None:
                points, colors, _ = self.map.arrays(limit=80000)
                data = np.column_stack((points, colors.astype(np.float32) / 255)).astype("<f4")
                self.cloud_cache = struct.pack("<4sIII", b"GGP1", len(points), self.sequence, 24) + data.tobytes()
            return self.cloud_cache

    def save_map(self, name):
        with self.lock:
            return self.maps.save(self.map, self.trajectory,
                {k: self.info[k] for k in ("source", "depth_kind", "intrinsics", "tracking", "frames_processed", "frames_fused", "frames_rejected")}, name)

    def load_map(self, map_id):
        with self.lock:
            if self.worker and self.worker.is_alive(): raise ValueError("Stop the scan before opening a saved map")
            model, poses, metadata = self.maps.load(map_id)
            self._reset("loaded")
            self.map, self.trajectory = model, list(poses)
            self.info.update(source=metadata["source"], depth_kind=metadata["depth_kind"], intrinsics=metadata["intrinsics"],
                map_mode="view_only", loaded_map=metadata, tracking={"state": "not_tracking_saved_map"},
                frames_processed=metadata.get("frames_processed", 0), frames_fused=metadata.get("frames_fused", 0))
            return self.state()
