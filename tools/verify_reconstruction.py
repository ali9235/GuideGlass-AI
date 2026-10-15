"""Reproducible real-camera acceptance test; never supplies ground truth to tracking."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
import numpy as np
from guideglass.engine import SpatialEngine
from guideglass.sources import RecordingSource
from guideglass.models import LocalModels, depth_preview


def groundtruth_matrix(row):
    x, y, z, w = row[4:8]
    pose = np.eye(4)
    pose[:3, :3] = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                      [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                      [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    pose[:3, 3] = row[1:4]
    return pose


def verify(frames=150, ai_frames=30):
    output = ROOT / ".data/reports"
    output.mkdir(parents=True, exist_ok=True)
    models = LocalModels(ROOT / "models")
    engine = SpatialEngine(ROOT, models=models)
    engine.info.update(source="sample", detector_enabled=False)
    source = RecordingSource(ROOT / ".data/samples/tum_xyz")
    observed, sizes, accepted, times = [], [], [], []
    begun = time.perf_counter()
    for i in range(min(frames, len(source.frames))):
        item = source.read()
        engine.process_frame(*item, detect=False)
        state = engine.state()
        sizes.append(state["point_count"])
        times.append(state["latency_ms"])
        if state["pose"] is not None:
            accepted.append((item[3], np.array(state["pose"])))
        if i < ai_frames: observed.append(item)
    elapsed = time.perf_counter() - begun
    if not accepted: raise RuntimeError("No real camera frames accepted")
    saved = engine.save_map("TUM real Kinect RGB-D acceptance test")
    before = engine.map.arrays()
    ply = output / "tum-real-rgbd-map.ply"
    ply.write_bytes(engine.maps.ply(saved["id"]))
    engine.load_map(saved["id"])
    after = engine.map.arrays()
    roundtrip = all(np.array_equal(a, b) for a, b in zip(before, after))
    # Independent evaluation ONLY AFTER reconstruction. No tracker consumes these poses.
    truth = np.loadtxt(source.folder / "groundtruth.txt")
    first_time, first_pose = accepted[0]
    first_truth = groundtruth_matrix(truth[np.argmin(abs(truth[:, 0] - first_time))])
    alignment = first_pose @ np.linalg.inv(first_truth)
    errors = []
    for timestamp, pose in accepted:
        row = truth[np.argmin(abs(truth[:, 0] - timestamp))]
        if abs(row[0] - timestamp) < .025:
            target = alignment @ groundtruth_matrix(row)
            errors.append(float(np.linalg.norm(pose[:3, 3] - target[:3, 3])))
    report = {"input":source.manifest["source"], "source_url":source.manifest["source_url"],
        "groundtruth_used_for_tracking":False, "test_type":"real_recorded_camera_not_live_hardware",
        "rgbd":{"frames_processed":len(sizes), "frames_fused":state["frames_fused"],
            "frames_rejected":state["frames_rejected"], "first_frame_points":sizes[0], "final_points":sizes[-1],
            "map_grew":sizes[-1]>sizes[0], "elapsed_seconds":round(elapsed,3),
            "mean_processing_fps":round(len(sizes)/elapsed,2), "median_latency_ms":round(float(np.median(times)),1),
            "camera_displacement_m":round(float(np.linalg.norm(accepted[-1][1][:3,3]-accepted[0][1][:3,3])),4),
            "trajectory_rmse_m_first_pose_alignment_no_scale_fit":round(float(np.sqrt(np.mean(np.square(errors)))),4) if errors else None,
            "trajectory_evaluation_matches":len(errors), "map_id":saved["id"], "save_load_exact":roundtrip,
            "ply":str(ply), "last_tracking":state["tracking"]},
        "limitations":["Kinect recording is not the user's camera or a live iPhone test",
            "Local RGB-D odometry; no globally optimized loop closure", "Nominal registered TUM intrinsics",
            "CPU inference; latency depends on hardware", "Monocular depth is learned indoor estimation, not measured scale"]}
    cv2.imwrite(str(output / "real-camera-input.jpg"), cv2.cvtColor(observed[0][0],cv2.COLOR_RGB2BGR))
    (output / "sensor-depth-preview.jpg").write_bytes(depth_preview(observed[0][1]))
    if ai_frames:
        print("RGB-D pass complete. Loading real local AI models...", flush=True)
        begun = time.perf_counter(); models.load(True, True)
        report["model_load_seconds"] = round(time.perf_counter()-begun,2)
        ai = SpatialEngine(ROOT, models=models)
        ai.info.update(source="sample_rgb", detector_enabled=True)
        depth_errors, scales, ai_times, detections = [], [], [], []
        for i, (rgb, measured, k, timestamp) in enumerate(observed):
            begun = time.perf_counter()
            predicted = models.depth(rgb)
            mask = (measured > .2) & (measured < 10) & np.isfinite(predicted) & (predicted > 0)
            depth_errors.append(float(np.median(abs(predicted[mask]-measured[mask])/measured[mask])))
            scales.append(float(np.median(predicted[mask]/measured[mask])))
            # Supply the actual predicted tensor through the model path, avoiding a duplicate inference.
            original = models.depth
            models.depth = lambda _rgb, d=predicted: d
            try: ai.process_frame(rgb, None, k, timestamp, detect=True)
            finally: models.depth = original
            ai_times.append(time.perf_counter()-begun)
            detections.extend(ai.info["detections"])
            if i == 0:
                (output / "ai-estimated-depth-preview.jpg").write_bytes(depth_preview(predicted))
                np.save(output / "ai-estimated-depth-meters.npy", predicted, allow_pickle=False)
        ai_state = ai.state()
        ai_saved = ai.save_map("AI estimated indoor depth — NOT measured scale") if ai_state["point_count"] else None
        if ai_saved: (output / "ai-estimated-map.ply").write_bytes(ai.maps.ply(ai_saved["id"]))
        report["ai"] = {"frames_processed":len(observed), "frames_fused":ai_state["frames_fused"],
            "frames_rejected":ai_state["frames_rejected"], "points":ai_state["point_count"],
            "median_end_to_end_latency_ms":round(float(np.median(ai_times))*1000,1),
            "end_to_end_processing_fps":round(len(observed)/sum(ai_times),2),
            "median_relative_depth_error_against_sensor":round(float(np.median(depth_errors)),4),
            "median_predicted_to_sensor_scale_ratio":round(float(np.median(scales)),4),
            "detected_labels":sorted({d["label"] for d in detections}),
            "detections_count_over_frames":len(detections),
            "motion_is_not_classified":all(d["motion"]=="unassessed" and not d["moving_hazard"] for d in detections),
            "last_tracking":ai_state["tracking"], "map_id":ai_saved["id"] if ai_saved else None,
            "depth_model":models.availability()["depth_model"], "depth_input_size":models.depth_size,
            "inference_device":models.device}
    report["passed_rgbd_acceptance"] = bool(report["rgbd"]["map_grew"] and roundtrip and state["frames_fused"] >= .8*len(sizes))
    (output / "verification.json").write_text(json.dumps(report, indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--frames",type=int,default=150)
    parser.add_argument("--ai-frames",type=int,default=30)
    args=parser.parse_args()
    result = verify(args.frames,args.ai_frames)
    if not result["passed_rgbd_acceptance"]:
        raise SystemExit("RGB-D acceptance failed; inspect .data/reports/verification.json")
