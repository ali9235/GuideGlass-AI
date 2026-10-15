"""Observed RGB-D -> camera pose -> bounded voxel point map.

Coordinate convention: OpenCV, x right, y down, z forward. T_world_camera
maps camera points into the first accepted camera's coordinate system.
No random geometry, hole filling, or unobserved surfaces are generated.
"""
from dataclasses import asdict, dataclass
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class Intrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    calibrated: bool = False
    source: str = "assumed_pinhole"

    def __post_init__(self):
        if any(not isinstance(v, int) or isinstance(v, bool) for v in (self.width, self.height)):
            raise ValueError("Camera dimensions must be integers")
        if not isinstance(self.calibrated, bool) or not isinstance(self.source, str) or len(self.source) > 120:
            raise ValueError("Invalid calibration provenance")
        if not (16 <= self.width <= 8192 and 16 <= self.height <= 8192):
            raise ValueError("Invalid camera dimensions")
        if not all(math.isfinite(v) for v in (self.fx, self.fy, self.cx, self.cy)):
            raise ValueError("Non-finite intrinsics")
        if not (0 < self.fx < 50000 and 0 < self.fy < 50000
                and 0 <= self.cx < self.width and 0 <= self.cy < self.height):
            raise ValueError("Invalid focal length or principal point")

    @classmethod
    def assumed(cls, width, height):
        return cls(width, height, .9 * width, .9 * width,
                   (width - 1) / 2, (height - 1) / 2)

    @classmethod
    def from_dict(cls, data):
        # Only rectified/registered pinhole inputs are supported in this version.
        if any(float(x) != 0 for x in data.get("distortion", [])):
            raise ValueError("Rectify RGB and register depth before using nonzero distortion calibration")
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

    def resized(self, width, height):
        sx, sy = width / self.width, height / self.height
        return Intrinsics(width, height, self.fx * sx, self.fy * sy,
                          (self.cx + .5) * sx - .5, (self.cy + .5) * sy - .5,
                          self.calibrated, self.source)

    @property
    def matrix(self):
        return np.array([[self.fx, 0, self.cx], [0, self.fy, self.cy], [0, 0, 1]], dtype=np.float64)

    def json(self):
        return asdict(self)


def transform_points(points, pose):
    return points @ pose[:3, :3].T + pose[:3, 3]


def depth_valid_mask(depth, minimum=.15, maximum=12.):
    valid = np.isfinite(depth) & (depth >= minimum) & (depth <= maximum)
    # Reject depth discontinuities rather than drawing stretched edges between surfaces.
    clean = np.where(valid, depth, 0).astype(np.float32)
    dx = np.abs(np.diff(clean, axis=1, prepend=clean[:, :1]))
    dy = np.abs(np.diff(clean, axis=0, prepend=clean[:1, :]))
    return valid & (dx < np.maximum(.08, clean * .08)) & (dy < np.maximum(.08, clean * .08))


def backproject(depth, rgb, intrinsics, stride=3, mask=None):
    if depth.shape != (intrinsics.height, intrinsics.width) or rgb.shape != (*depth.shape, 3):
        raise ValueError("RGB/depth/calibration must have matching registered dimensions")
    if not 1 <= stride <= 32:
        raise ValueError("Invalid sampling stride")
    valid = depth_valid_mask(depth)
    if mask is not None:
        valid &= mask.astype(bool)
    v, u = np.mgrid[0:depth.shape[0]:stride, 0:depth.shape[1]:stride]
    keep = valid[v, u]
    u, v = u[keep], v[keep]
    z = depth[v, u]
    xyz = np.column_stack(((u - intrinsics.cx) * z / intrinsics.fx,
                           (v - intrinsics.cy) * z / intrinsics.fy, z)).astype(np.float32)
    return xyz, rgb[v, u].astype(np.uint8)


class VoxelMap:
    """Running mean per observed voxel; hard memory and browser point limits."""
    def __init__(self, voxel_size=.035, max_points=160000):
        if not .005 <= voxel_size <= .25 or not 100 <= max_points <= 300000:
            raise ValueError("Invalid map limits")
        self.voxel_size, self.max_points = float(voxel_size), int(max_points)
        self.cells = {}
        self.capacity_reached = False

    def fuse(self, xyz, colors):
        if len(xyz) != len(colors):
            raise ValueError("Point/color count mismatch")
        keep = np.isfinite(xyz).all(axis=1) & (np.abs(xyz).max(axis=1) < 200)
        xyz, colors = xyz[keep], colors[keep]
        if not len(xyz):
            return
        keys, inverse = np.unique(np.floor(xyz / self.voxel_size).astype(np.int32), axis=0, return_inverse=True)
        counts = np.bincount(inverse)
        sums = np.zeros((len(keys), 6), np.float64)
        np.add.at(sums, inverse, np.column_stack((xyz, colors)))
        means = sums / counts[:, None]
        for key, value in zip(keys, means):
            k = tuple(int(x) for x in key)
            previous = self.cells.get(k)
            if previous is None:
                if len(self.cells) >= self.max_points:
                    self.capacity_reached = True
                    continue
                self.cells[k] = (value, 1)
            else:
                mean, n = previous
                n = min(n, 99)
                self.cells[k] = ((mean * n + value) / (n + 1), n + 1)

    def arrays(self, limit=None):
        values = list(self.cells.values())
        if limit and len(values) > limit:
            values = [values[i] for i in np.linspace(0, len(values) - 1, limit, dtype=int)]
        if not values:
            return np.empty((0, 3), np.float32), np.empty((0, 3), np.uint8), np.empty(0, np.uint16)
        data = np.stack([v[0] for v in values])
        return data[:, :3].astype(np.float32), np.clip(data[:, 3:], 0, 255).astype(np.uint8), np.array([v[1] for v in values], np.uint16)

    def restore(self, xyz, colors, counts, keys=None):
        if len(xyz) > self.max_points or xyz.shape != colors.shape or len(xyz) != len(counts):
            raise ValueError("Invalid saved point arrays")
        if not np.isfinite(xyz).all() or np.any(np.abs(xyz) >= 200):
            raise ValueError("Invalid saved coordinates")
        if keys is None:
            keys = np.floor(xyz / self.voxel_size).astype(np.int32)
        if keys.shape != xyz.shape or not np.issubdtype(keys.dtype, np.integer):
            raise ValueError("Invalid voxel keys")
        # Preserve voxel identity: float32 serialization can round a centroid
        # across a cell boundary. Re-quantizing it silently lost points.
        if len(np.unique(keys, axis=0)) != len(keys):
            raise ValueError("Duplicate voxel keys in saved map; regenerate a legacy map")
        if np.any(np.abs(xyz - (keys + .5) * self.voxel_size) > self.voxel_size / 2 + 1e-4):
            raise ValueError("Saved coordinates do not belong to their voxel keys")
        self.cells.clear()
        for p, c, n, raw_key in zip(xyz, colors, counts, keys):
            key = tuple(int(x) for x in raw_key)
            self.cells[key] = (np.concatenate((p, c)).astype(np.float64), max(1, min(int(n), 100)))


class PoseTracker:
    """ORB + registered previous depth + PnP RANSAC; reject bad poses.

Recent keyframes permit local relocalization. This is local visual odometry,
not globally optimized SLAM: there is no loop-closure bundle adjustment.
"""
    def __init__(self):
        self.orb = cv2.ORB_create(nfeatures=1800, fastThreshold=12, edgeThreshold=19)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.reference = None
        self.keyframes = []
        self.accepted = 0

    def _frame(self, rgb, depth, intrinsics, mask, timestamp):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        valid = depth_valid_mask(depth) & mask
        keypoints, descriptors = self.orb.detectAndCompute(gray, (valid * 255).astype(np.uint8))
        return {"keypoints": keypoints, "descriptors": descriptors, "depth": depth.copy(),
                "intrinsics": intrinsics, "timestamp": timestamp, "pose": None}

    def update(self, rgb, depth, intrinsics, mask, timestamp, estimated=False):
        current = self._frame(rgb, depth, intrinsics, mask, timestamp)
        if self.reference is None:
            if current["descriptors"] is None or len(current["keypoints"]) < 30:
                return None, {"state": "lost", "reason": "insufficient_texture", "inliers": 0}
            current["pose"] = np.eye(4)
            self.reference = current
            self.keyframes = [current]
            self.accepted = 1
            return current["pose"], {"state": "initialized", "reason": "first_observed_frame", "inliers": 0,
                                     "confidence": None, "confidence_kind": "not_a_probability"}
        candidates = [self.reference] + [frame for frame in reversed(self.keyframes)
                                        if frame is not self.reference][:6]
        best_failure = {"state": "lost", "reason": "not_enough_matches", "inliers": 0}
        for index, reference in enumerate(candidates):
            pose, metrics = self._estimate(reference, current, estimated)
            if pose is None:
                if metrics.get("inliers", 0) >= best_failure.get("inliers", 0):
                    best_failure = metrics
                continue
            current["pose"] = pose
            self.reference = current
            self.accepted += 1
            if self.accepted % 4 == 0:
                self.keyframes.append(current)
                self.keyframes = self.keyframes[-16:]
            metrics["state"] = "tracking" if index == 0 else "relocalized"
            return pose, metrics
        # Keep last accepted reference and pose. A lost frame NEVER enters the map.
        return None, best_failure

    def _estimate(self, reference, current, estimated):
        failure = {"state": "lost", "reason": "not_enough_matches", "inliers": 0}
        if current["descriptors"] is None or reference["descriptors"] is None:
            return None, failure
        pairs = self.matcher.knnMatch(reference["descriptors"], current["descriptors"], k=2)
        good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < .72 * pair[1].distance]
        # Unique image correspondences prevent duplicated matches inflating confidence.
        unique = {}
        for match in sorted(good, key=lambda m: m.distance):
            unique.setdefault(match.trainIdx, match)
        good = list(unique.values())
        if len(good) < 25:
            return None, failure
        uv0 = np.array([reference["keypoints"][m.queryIdx].pt for m in good], np.float64)
        uv1 = np.array([current["keypoints"][m.trainIdx].pt for m in good], np.float64)
        pixels = np.rint(uv0).astype(int)
        z = reference["depth"][pixels[:, 1], pixels[:, 0]]
        k = reference["intrinsics"]
        xyz = np.column_stack(((uv0[:, 0] - k.cx) * z / k.fx, (uv0[:, 1] - k.cy) * z / k.fy, z))
        valid = np.isfinite(xyz).all(axis=1) & (z > .15) & (z < 12)
        xyz, uv1 = xyz[valid], uv1[valid]
        if len(xyz) < 25:
            return None, failure
        ok, rvec, tvec, ids = cv2.solvePnPRansac(xyz, uv1, current["intrinsics"].matrix, None,
            iterationsCount=150, reprojectionError=2.5, confidence=.999, flags=cv2.SOLVEPNP_EPNP)
        if not ok or ids is None or len(ids) < 22:
            return None, failure
        ids = ids.ravel()
        rvec, tvec = cv2.solvePnPRefineLM(xyz[ids], uv1[ids], current["intrinsics"].matrix, None, rvec, tvec)
        projected, _ = cv2.projectPoints(xyz[ids], rvec, tvec, current["intrinsics"].matrix, None)
        residual = np.linalg.norm(projected[:, 0] - uv1[ids], axis=1)
        rotation, _ = cv2.Rodrigues(rvec)
        angle = math.degrees(math.acos(float(np.clip((np.trace(rotation) - 1) / 2, -1, 1))))
        translation = float(np.linalg.norm(tvec))
        ratio = len(ids) / len(xyz)
        metrics = {"state": "lost", "reason": "geometry_rejected", "matches": len(xyz),
                   "inliers": len(ids), "inlier_ratio": round(ratio, 4),
                   "reprojection_median_px": round(float(np.median(residual)), 4),
                   "rotation_degrees": round(angle, 3), "translation": round(translation, 5),
                   "confidence": round(min(ratio, len(ids) / 100) * max(0, 1 - np.median(residual) / 3), 3),
                   "confidence_kind": "engineering_quality_score_not_probability"}
        if ratio < .35 or np.median(residual) > 1.8 or angle > 40 or translation > (1.2 if estimated else .75):
            return None, metrics
        # Check spatial spread, so one tiny texture patch cannot anchor the whole frame.
        span = np.ptp(uv1[ids], axis=0)
        if span[0] < current["intrinsics"].width * .18 or span[1] < current["intrinsics"].height * .15:
            metrics["reason"] = "matches_cover_too_little_image"
            return None, metrics
        transformed = xyz[ids] @ rotation.T + tvec.ravel()
        px = np.rint(uv1[ids]).astype(int)
        observed = current["depth"][px[:, 1], px[:, 0]]
        usable = np.isfinite(observed) & (observed > .15)
        if usable.sum() < 15:
            metrics["reason"] = "insufficient_depth_overlap"
            return None, metrics
        relative = np.abs(transformed[usable, 2] - observed[usable]) / np.maximum(observed[usable], .2)
        metrics["depth_relative_median"] = round(float(np.median(relative)), 4)
        if np.median(relative) > (.24 if estimated else .07):
            metrics["reason"] = "depth_scale_or_registration_inconsistent"
            return None, metrics
        delta = np.eye(4)
        delta[:3, :3], delta[:3, 3] = rotation, tvec.ravel()
        pose = reference["pose"] @ np.linalg.inv(delta)
        if not np.isfinite(pose).all():
            return None, metrics
        metrics["reason"] = "accepted_ransac_and_depth_checks"
        return pose, metrics


def detection_locations(detections, depth, intrinsics, pose, depth_kind):
    result = []
    for detection in detections:
        item = dict(detection, motion="unassessed", moving_hazard=False, world_position=None)
        x1, y1, x2, y2 = detection["box"]
        left, top = max(0, int(x1 + .3 * (x2 - x1))), max(0, int(y1 + .3 * (y2 - y1)))
        right, bottom = min(depth.shape[1], int(x2 - .3 * (x2 - x1))), min(depth.shape[0], int(y2 - .3 * (y2 - y1)))
        roi = depth[top:bottom, left:right]
        values = roi[np.isfinite(roi) & (roi > .15) & (roi < 12)]
        if pose is not None and values.size >= 20:
            z = float(np.median(values)); spread = float(np.percentile(values, 75) - np.percentile(values, 25))
            if spread < max(.2, z * .3):
                u, v = (x1 + x2) / 2, (y1 + y2) / 2
                point = np.array([[(u - intrinsics.cx) * z / intrinsics.fx, (v - intrinsics.cy) * z / intrinsics.fy, z]])
                item.update(world_position=transform_points(point, pose)[0].tolist(),
                    extent=[max(.05, (x2 - x1) * z / intrinsics.fx), max(.05, (y2 - y1) * z / intrinsics.fy), max(.06, spread)],
                    depth=z, depth_kind=depth_kind, depth_iqr=spread,
                    spatial_quality="estimated_surface_location_not_object_volume")
        result.append(item)
    return result
