import argparse
from collections import Counter
import csv
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import shutil
import time

from .core import EventEngine, validate

VIDEO_EXTENSIONS = {".mpg", ".mpeg", ".mp4", ".avi", ".mov", ".mkv", ".m4v"}


def writer(path, fields):
    handle = path.open("w", newline="", encoding="utf-8")
    out = csv.DictWriter(handle, fieldnames=fields)
    out.writeheader()
    return handle, out


def annotate(args):
    import cv2
    from .annotation import make_html
    cap = cv2.VideoCapture(str(args.video))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, args.at * 1000)
        ok, frame = cap.read()
        if not ok:
            raise ValueError("cannot decode annotation frame")
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            raise ValueError("cannot encode annotation image")
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValueError(f"refusing to overwrite {target}")
        target.write_text(make_html(encoded.tobytes(), frame.shape[1], frame.shape[0]), encoding="utf-8")
        print(f"Open {target.resolve()} in your local browser; draw regions and download scene.json.")
    finally:
        cap.release()


def discover(inputs):
    files = []
    for value in inputs:
        p = Path(value)
        if p.is_dir():
            files.extend(x for x in sorted(p.rglob("*")) if x.is_file() and x.suffix.lower() in VIDEO_EXTENSIONS)
        elif p.is_file():
            files.append(p)
        else:
            raise ValueError(f"input does not exist: {p}")
    files = list(dict.fromkeys(p.resolve() for p in files))
    if not files:
        raise ValueError("no videos found")
    return files


def export(args):
    source = Path(args.run)
    if not source.is_dir():
        raise ValueError(f"run directory does not exist: {source}")
    candidates = [source] if (source / "metadata.json").exists() else sorted(p for p in source.iterdir() if p.is_dir() and not p.name.startswith("."))
    completed = []
    for folder in candidates:
        meta_path = folder / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not meta.get("complete"):
            continue
        for name in ("summary.csv", "occupancy_summary.csv"):
            if not (folder / name).is_file():
                raise ValueError(f"missing {name} in completed run {folder}")
        completed.append((folder, meta))
    if not completed:
        raise ValueError("no completed runs to export")
    target = Path(args.output)
    if target.exists():
        raise ValueError(f"refusing to overwrite export directory: {target}")
    target.mkdir(parents=True)
    for folder, meta in completed:
        out = target / folder.name
        out.mkdir()
        for name in ("summary.csv", "occupancy_summary.csv"):
            shutil.copyfile(folder / name, out / name)
        meta["settings"]["source"] = Path(meta["settings"]["source"]).name
        meta["settings"]["model"] = Path(meta["settings"]["model"]).name
        (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(completed)} completed runs to {target}. Review counts before committing.")


def analyze(args):
    import cv2
    from ultralytics import YOLO
    config = json.loads(Path(args.scene).read_text(encoding="utf-8"))
    validate(config)
    files = discover(args.inputs)
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    loaded_model = YOLO(args.model)
    model_path = Path(loaded_model.ckpt_path or args.model)
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest() if model_path.is_file() else None
    versions = {k: importlib.metadata.version(k) for k in ("traffic-los", "ultralytics", "opencv-python", "numpy", "torch", "torchvision", "lap")}
    implementation_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    for video in files:
        key = hashlib.sha256(str(video).encode()).hexdigest()[:8]
        target = root / f"{video.stem}_{key}"
        metadata = {"source": str(video), "size": video.stat().st_size, "mtime_ns": video.stat().st_mtime_ns,
                    "scene": config, "model": args.model, "model_sha256": model_hash, "versions": versions,
                    "implementation_sha256": implementation_hash,
                    "tracker": args.tracker, "confidence": args.conf, "imgsz": args.imgsz,
                    "classes": args.classes, "bin_seconds": args.bin_seconds,
                    "deadband_px": args.deadband, "max_gap_s": args.max_gap,
                    "track_sample_seconds": args.track_sample_seconds, "device": args.device,
                    "duration_limit_s": args.duration, "overlay_seconds": args.overlay_seconds}
        if target.exists():
            saved = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
            if args.resume and saved.get("settings") == metadata and saved.get("complete"):
                print(f"Skip completed: {video.name}")
                continue
            raise ValueError(f"output exists or settings changed: {target}; choose a new --output directory")
        partial = root / f".{target.name}.partial"
        if partial.exists():
            # Preserve interrupted output for audit instead of deleting user files.
            backup = root / f".{target.name}.interrupted-{time.time_ns()}"
            partial.rename(backup)
            print(f"Preserved interrupted output: {backup}; restarting video from frame 0")
        partial.mkdir()
        (partial / "metadata.json").write_text(json.dumps({"settings": metadata, "complete": False}, indent=2), encoding="utf-8")
        cap = cv2.VideoCapture(str(video))
        handles = []
        overlay = None
        try:
            if not cap.isOpened():
                raise ValueError(f"cannot open video: {video}")
            fps = cap.get(cv2.CAP_PROP_FPS)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if not math.isfinite(fps) or fps <= 0:
                raise ValueError("invalid video FPS; transcode to constant FPS before analysis")
            # New model instance gives each source an independent tracking session.
            model = YOLO(str(model_path))
            selected = [i for i, name in model.names.items() if name in args.classes]
            missing = set(args.classes) - set(model.names.values())
            if missing:
                raise ValueError(f"model does not contain classes: {sorted(missing)}")
            engine = EventEngine(config, args.deadband, args.max_gap)
            eh, ew = writer(partial / "events.csv", ["kind", "time_s", "track_id", "class", "line", "direction", "entry", "exit"])
            handles.append(eh)
            th, tw = writer(partial / "tracks.csv", ["frame", "time_s", "track_id", "class", "confidence", "x1", "y1", "x2", "y2", "anchor_x", "anchor_y"])
            handles.append(th)
            oh, ow = writer(partial / "occupancy.csv", ["time_s", "zone", "class", "visible_count"])
            handles.append(oh)
            hh, hw = writer(partial / "headways.csv", ["time_s", "line", "direction", "previous_track_id", "track_id", "class", "headway_s"])
            handles.append(hh)
            last_crossing = {}
            summary = Counter()
            zone_summary = {}
            index = 0
            last_sample = last_occupancy = -float("inf")
            started = last_log = time.monotonic()
            last_pts = -1.0
            time_basis = None
            duration_limited = False
            last_processed_time = 0.0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                h, w = frame.shape[:2]
                if (w, h) != (config["width"], config["height"]):
                    raise ValueError("video dimensions differ from annotated frame; create a matching scene")
                pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if time_basis is None:
                    time_basis = "opencv_pts" if pts == 0 else "frame_index/fps"
                if time_basis == "opencv_pts":
                    if pts <= last_pts:
                        raise ValueError("nonmonotonic video timestamps; transcode to constant FPS")
                    timestamp = pts
                    last_pts = pts
                else:
                    timestamp = index / fps
                if args.duration is not None and timestamp >= args.duration:
                    duration_limited = True
                    break
                results = model.track(frame, persist=True, tracker=args.tracker + ".yaml", classes=selected,
                                      conf=args.conf, imgsz=args.imgsz, device=args.device, verbose=False)
                boxes = results[0].boxes
                detections = []
                if boxes is not None and boxes.id is not None:
                    for xyxy, tid, cls, confidence in zip(boxes.xyxy.cpu().tolist(), boxes.id.cpu().tolist(),
                                                          boxes.cls.cpu().tolist(), boxes.conf.cpu().tolist()):
                        x1, y1, x2, y2 = xyxy
                        name = model.names[int(cls)]
                        detections.append({"id": int(tid), "class": name, "point": ((x1 + x2) / 2, y2)})
                        if timestamp - last_sample >= args.track_sample_seconds:
                            tw.writerow(dict(zip(tw.fieldnames, [index, round(timestamp, 4), int(tid), name,
                                          round(confidence, 4), x1, y1, x2, y2, (x1 + x2) / 2, y2])))
                events, occupancy = engine.update(timestamp, detections)
                for event in events:
                    ew.writerow(event)
                    if event["kind"] == "crossing" and event["class"] in ("car", "bus", "truck", "motorcycle"):
                        stream = (event["line"], event["direction"])
                        prev = last_crossing.get(stream)
                        if prev:
                            hw.writerow({"time_s": event["time_s"], "line": event["line"],
                                         "direction": event["direction"], "previous_track_id": prev[1],
                                         "track_id": event["track_id"], "class": event["class"],
                                         "headway_s": event["time_s"] - prev[0]})
                        last_crossing[stream] = (event["time_s"], event["track_id"])
                    bin_index = int(event["time_s"] // args.bin_seconds)
                    summary[(bin_index, event["kind"], event["class"], event["line"],
                             event["direction"], event["entry"], event["exit"])] += 1
                if timestamp - last_sample >= args.track_sample_seconds:
                    last_sample = timestamp
                if timestamp - last_occupancy >= 1:
                    for zone in config.get("zones", []):
                        for name in args.classes:
                            count = occupancy[(zone["name"], name)]
                            ow.writerow({"time_s": round(timestamp, 4), "zone": zone["name"], "class": name,
                                         "visible_count": count})
                            key = (int(timestamp // args.bin_seconds), zone["name"], name)
                            accum = zone_summary.setdefault(key, [0, 0, 0])
                            accum[0] += count
                            accum[1] += 1
                            accum[2] = max(accum[2], count)
                    last_occupancy = timestamp
                if timestamp < args.overlay_seconds:
                    if overlay is None:
                        overlay = cv2.VideoWriter(str(partial / "overlay.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                        if not overlay.isOpened():
                            raise ValueError("cannot encode overlay.mp4 on this OpenCV installation")
                    image = results[0].plot()
                    for line in config.get("lines", []):
                        a, b = [tuple(round(v) for v in p) for p in line["points"]]
                        cv2.line(image, a, b, (0, 255, 255), 2)
                        cv2.putText(image, line["name"], a, cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 255), 1)
                    for zone in config.get("zones", []):
                        import numpy as np
                        cv2.polylines(image, [np.array(zone["points"], dtype=np.int32)], True, (255, 255, 0), 2)
                    cv2.putText(image, f"t={timestamp:.2f}s", (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 2)
                    overlay.write(image)
                last_processed_time = timestamp
                index += 1
                if time.monotonic() - last_log >= 10:
                    rate = index / (time.monotonic() - started)
                    print(f"{video.name}: {index}/{total or '?'} frames; {rate:.1f} processing FPS", flush=True)
                    for handle in handles:
                        handle.flush()
                    last_log = time.monotonic()
            if index == 0:
                raise ValueError("zero frames decoded")
            if not duration_limited and total > 0 and index < total:
                raise ValueError(f"decode ended early: {index}/{total} frames; partial results preserved")
            sh, sw = writer(partial / "summary.csv", ["bin_start_s", "bin_end_s", "observed_end_s", "kind", "class", "line", "direction", "entry", "exit", "count"])
            handles.append(sh)
            observed_end = last_processed_time + 1 / fps
            # Include observed zero-count bins for configured lines and detected movement types.
            series = {k[1:] for k in summary}
            for line in config.get("lines", []):
                directions = ("positive", "negative") if line.get("direction", "both") == "both" else (line["direction"],)
                for cls in set(line.get("classes") or args.classes) & set(args.classes):
                    for direction in directions:
                        series.add(("crossing", cls, line["name"], direction, "", ""))
            for bin_index in range(math.ceil(observed_end / args.bin_seconds)):
                for fields in sorted(series):
                    start = bin_index * args.bin_seconds
                    sw.writerow(dict(zip(sw.fieldnames, [start, start + args.bin_seconds,
                                 min(start + args.bin_seconds, observed_end), *fields, summary[(bin_index, *fields)]])))
            zh, zw = writer(partial / "occupancy_summary.csv", ["bin_start_s", "bin_end_s", "observed_end_s", "zone", "class", "samples", "mean_visible_count", "max_visible_count"])
            handles.append(zh)
            for (bin_index, zone, cls), (sum_count, samples, maximum) in sorted(zone_summary.items()):
                start = bin_index * args.bin_seconds
                zw.writerow(dict(zip(zw.fieldnames, [start, start + args.bin_seconds,
                             min(start + args.bin_seconds, observed_end), zone, cls, samples,
                             sum_count / samples, maximum])))
            result = {"settings": metadata, "complete": True, "decoded_frames": index,
                      "source_fps": fps, "time_basis": time_basis, "observed_duration_s": observed_end,
                      "termination": "duration_limit" if duration_limited else "end_of_stream",
                      "processing_seconds": time.monotonic() - started}
            (partial / "metadata.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            for handle in handles:
                handle.close()
            if overlay is not None:
                overlay.release()
            partial.rename(target)
            print(f"Completed: {target}")
        finally:
            cap.release()
            for handle in handles:
                handle.close()
            if overlay is not None:
                overlay.release()


def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return result


def main():
    parser = argparse.ArgumentParser(description="Local video → detection → tracking → auditable CSV")
    sub = parser.add_subparsers(dest="command", required=True)
    annotation = sub.add_parser("annotate", help="export an offline browser annotation page")
    annotation.add_argument("video")
    annotation.add_argument("--at", type=float, default=0)
    annotation.add_argument("--output", default="scene-annotator.html")
    annotation.set_defaults(func=annotate)
    exporting = sub.add_parser("export", help="copy completed summaries and portable metadata for GitHub")
    exporting.add_argument("run")
    exporting.add_argument("--output", required=True)
    exporting.set_defaults(func=export)
    analysis = sub.add_parser("analyze", help="stream one or more videos to CSV")
    analysis.add_argument("inputs", nargs="+")
    analysis.add_argument("--scene", required=True)
    analysis.add_argument("--output", default="runs/analysis")
    analysis.add_argument("--model", default="yolo11n.pt")
    analysis.add_argument("--tracker", choices=["bytetrack", "botsort"], default="bytetrack")
    analysis.add_argument("--device", default="cpu")
    analysis.add_argument("--imgsz", type=int, default=960)
    analysis.add_argument("--conf", type=float, default=0.25)
    analysis.add_argument("--classes", nargs="+", default=["person", "bicycle", "car", "motorcycle", "bus", "truck"])
    analysis.add_argument("--bin-seconds", type=positive, default=900)
    analysis.add_argument("--deadband", type=positive, default=3)
    analysis.add_argument("--max-gap", type=positive, default=1)
    analysis.add_argument("--track-sample-seconds", type=positive, default=0.5)
    analysis.add_argument("--resume", action="store_true")
    analysis.add_argument("--duration", type=positive, help="analyze only the first N seconds for validation")
    analysis.add_argument("--overlay-seconds", type=float, default=0, help="save first N seconds with tracking IDs for manual review")
    analysis.set_defaults(func=analyze)
    args = parser.parse_args()
    if args.command == "analyze" and (not 0 < args.conf < 1 or args.imgsz <= 0 or not math.isfinite(args.overlay_seconds) or args.overlay_seconds < 0):
        parser.error("conf must be between 0 and 1; imgsz positive; overlay-seconds finite and nonnegative")
    try:
        args.func(args)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
