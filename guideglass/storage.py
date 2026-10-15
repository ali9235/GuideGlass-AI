"""Versioned, bounded map persistence without executable pickle data."""
import io
import json
from pathlib import Path
import re
import time
import uuid
import zipfile

import numpy as np

from .geometry import VoxelMap


class MapStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, map_id):
        if not re.fullmatch(r"[0-9a-f]{32}", str(map_id)):
            raise ValueError("Invalid map ID")
        return self.root / (map_id + ".npz")

    def save(self, voxel_map, trajectory, metadata, name=""):
        xyz, rgb, counts = voxel_map.arrays()
        if not len(xyz):
            raise ValueError("No observed points to save")
        map_id = uuid.uuid4().hex
        info = dict(metadata, schema=2, id=map_id, name=str(name).strip()[:80] or "Observed map",
                    saved_at=time.time(), point_count=len(xyz), voxel_size=voxel_map.voxel_size,
                    frame_count=len(trajectory), coordinate_convention="OpenCV_x_right_y_down_z_forward",
                    resume_mode="view_only_start_new_scan_to_map", global_loop_optimization=False)
        buffer = io.BytesIO()
        np.savez_compressed(buffer, xyz=xyz, rgb=rgb, counts=counts,
            voxel_keys=np.asarray(list(voxel_map.cells), dtype=np.int32).reshape((-1, 3)),
            trajectory=np.asarray(trajectory, dtype=np.float64).reshape((-1, 4, 4)),
            metadata=np.frombuffer(json.dumps(info, ensure_ascii=False, allow_nan=False).encode("utf-8"), np.uint8))
        path = self.path(map_id); temporary = path.with_suffix(".part")
        temporary.write_bytes(buffer.getvalue()); temporary.replace(path)
        manifest = path.with_suffix(".json")
        manifest_temporary = manifest.with_suffix(".json.part")
        manifest_temporary.write_text(json.dumps(info, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        manifest_temporary.replace(manifest)
        return info

    def list(self):
        result = []
        for path in sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if self.path(item["id"]).is_file():
                    result.append(item)
            except (ValueError, KeyError, OSError):
                continue
        return result

    def load(self, map_id):
        path = self.path(map_id)
        if not path.is_file() or path.stat().st_size > 30000000:
            raise ValueError("Map missing or too large")
        try:
            with zipfile.ZipFile(path) as archive:
                if sum(i.file_size for i in archive.infolist()) > 50000000:
                    raise ValueError("Expanded map exceeds memory budget")
        except zipfile.BadZipFile as error:
            raise ValueError("Saved map archive is corrupt") from error
        with np.load(path, allow_pickle=False) as saved:
            meta_bytes = saved["metadata"]
            if meta_bytes.dtype != np.uint8 or meta_bytes.size > 100000:
                raise ValueError("Invalid map metadata")
            info = json.loads(meta_bytes.tobytes())
            if info.get("schema") not in (1, 2) or info.get("id") != map_id:
                raise ValueError("Unsupported or mismatched map schema")
            xyz, colors, counts, poses = (saved[key] for key in ("xyz", "rgb", "counts", "trajectory"))
            if (xyz.ndim != 2 or xyz.shape[1] != 3 or colors.dtype != np.uint8 or counts.ndim != 1
                    or counts.dtype != np.uint16 or xyz.dtype != np.float32 or np.any(counts < 1)):
                raise ValueError("Invalid point map")
            if poses.ndim != 3 or poses.shape[1:] != (4, 4) or len(poses) > 20000 or not np.isfinite(poses).all():
                raise ValueError("Invalid camera trajectory")
            model = VoxelMap(info["voxel_size"])
            model.restore(xyz, colors, counts, saved["voxel_keys"] if info["schema"] == 2 else None)
        return model, poses, info

    def ply(self, map_id):
        model, _, _ = self.load(map_id)
        xyz, colors, _ = model.arrays()
        header = ("ply\nformat binary_little_endian 1.0\ncomment GuideGlass observed points; OpenCV coordinate system\n"
                  f"element vertex {len(xyz)}\nproperty float x\nproperty float y\nproperty float z\n"
                  "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n").encode("ascii")
        vertices = np.empty(len(xyz), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                           ("r", "u1"), ("g", "u1"), ("b", "u1")])
        for i, key in enumerate(("x", "y", "z")): vertices[key] = xyz[:, i]
        for i, key in enumerate(("r", "g", "b")): vertices[key] = colors[:, i]
        return header + vertices.tobytes()
