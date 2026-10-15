"""Download pinned, public assets. No camera images are uploaded anywhere."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def download(url, path, max_bytes, expected_sha256=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size > 0:
        if not expected_sha256 or hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256:
            return path
    temporary = path.with_suffix(path.suffix + ".part")
    total = 0
    with urlopen(Request(url, headers={"User-Agent": "GuideGlass-local-setup/0.2"}), timeout=45) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("Download exceeds its documented size limit")
            output.write(chunk)
    if expected_sha256 and hashlib.sha256(temporary.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("Asset checksum mismatch")
    temporary.replace(path)
    return path


def web():
    # Local vendoring means the iPhone does not need CDN access during use.
    base = "https://cdn.jsdelivr.net/npm/three@0.170.0/"
    for source, target in [("build/three.module.js", "three.module.js"),
                           ("examples/jsm/controls/OrbitControls.js", "OrbitControls.js"), ("LICENSE", "THREE-LICENSE.txt")]:
        download(base + source, ROOT / "vendor" / target, 2000000)
    print("Three.js r170 and OrbitControls installed locally.", flush=True)


def models():
    from guideglass.models import DEPTH_MODEL, DEPTH_REVISION, DETECTOR_FILE
    from huggingface_hub import snapshot_download
    snapshot_download(DEPTH_MODEL, revision=DEPTH_REVISION, local_dir=ROOT / "models" / "depth",
                      allow_patterns=["*.json", "*.safetensors", "README.md"])
    download("https://download.pytorch.org/models/" + DETECTOR_FILE, ROOT / "models" / DETECTOR_FILE, 25000000)
    path = ROOT / "models" / DETECTOR_FILE
    if not hashlib.sha256(path.read_bytes()).hexdigest().startswith("a79551df"):
        raise ValueError("Torchvision official weight hash did not match")
    print("Local depth and COCO detection weights ready.", flush=True)


def tum_sample():
    import numpy as np
    import cv2
    folder = ROOT / ".data" / "samples" / "tum_xyz"
    if (folder / "manifest.json").is_file():
        print("Existing TUM recording retained.", flush=True)
        return
    url = "https://webshare.cvg.cit.tum.de/g/rgbd/dataset/freiburg1/rgbd_dataset_freiburg1_xyz.tgz"
    archive = download(url, ROOT / ".data" / "downloads" / "rgbd_dataset_freiburg1_xyz.tgz", 600000000)
    folder.mkdir(parents=True, exist_ok=True)
    prefix = "rgbd_dataset_freiburg1_xyz/"
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        names = {m.name: m for m in members if m.isfile()}
        def read_index(name):
            raw = tar.extractfile(names[prefix + name]).read().decode("utf-8")
            return [line.split() for line in raw.splitlines() if line and not line.startswith("#")], raw
        rgb, _ = read_index("rgb.txt")
        depth, _ = read_index("depth.txt")
        _, groundtruth = read_index("groundtruth.txt")
        depth_times = np.array([float(row[0]) for row in depth])
        frames, selected, used = [], set(), set()
        for row in rgb[:450:3]:
            timestamp = float(row[0]); nearest = int(np.argmin(np.abs(depth_times - timestamp)))
            if abs(depth_times[nearest] - timestamp) > .025 or nearest in used:
                continue
            used.add(nearest)
            frames.append({"timestamp": timestamp, "rgb": row[1], "depth": depth[nearest][1],
                           "depth_timestamp": float(depth[nearest][0])})
            selected.update((prefix + row[1], prefix + depth[nearest][1]))
        # Only explicit regular files beneath this dataset prefix are extracted.
        for member in members:
            if member.name in selected:
                relative = Path(member.name[len(prefix):])
                target = (folder / relative).resolve()
                if not target.is_relative_to(folder.resolve()) or member.size > 3000000:
                    raise ValueError("Unsafe dataset member")
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    (folder / "groundtruth.txt").write_text(groundtruth, encoding="utf-8")
    manifest = {"source": "TUM RGB-D Freiburg1 xyz: real Kinect camera recording",
        "source_url": url, "citation": "Sturm et al., A Benchmark for the Evaluation of RGB-D SLAM Systems, IROS 2012",
        "depth_kind": "sensor_metric", "depth_divisor": 5000.,
        "intrinsics": {"width": 640, "height": 480, "fx": 525., "fy": 525., "cx": 319.5, "cy": 239.5,
                       "calibrated": False, "source": "TUM_recommended_registered_ROS_intrinsics"},
        "calibration_note": "TUM recommends ROS default intrinsics for its pre-registered depth; not a calibration of the user's camera.",
        "groundtruth_use": "evaluation only; NEVER fed into the pose tracker", "frames": frames}
    writer = cv2.VideoWriter(str(folder / "recorded-rgb.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 480))
    if not writer.isOpened():
        raise RuntimeError("Could not create test video")
    for frame in frames:
        image = cv2.imread(str(folder / frame["rgb"]))
        if image is None:
            raise RuntimeError("Missing real camera frame")
        writer.write(image)
    writer.release()
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Real TUM recording prepared: {len(frames)} registered RGB-D frames and RGB video.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--sample", action="store_true", help="Download the 0.47GB public TUM recording and extract a bounded subset")
    args = parser.parse_args()
    if args.web: web()
    if args.models: models()
    if args.sample: tum_sample()
