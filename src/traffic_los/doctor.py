"""Readiness check: decode video and run actual model inference/tracking."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import tempfile


def check(model_path, device):
    import cv2
    import numpy as np
    import torch
    import ultralytics
    from ultralytics import YOLO

    if device != "cpu" and device != "mps":
        if not torch.cuda.is_available():
            raise ValueError("CUDA is unavailable in this Python environment; check the NVIDIA driver and the installed PyTorch wheel")
    if device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS is unavailable")
    model_path = Path(model_path).resolve()
    model_path.parent.mkdir(parents=True, exist_ok=True)
    # Ultralytics uses its official release download when this file is absent.
    image_path = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
    image = cv2.imdecode(np.frombuffer(image_path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("packaged model test image missing")
    h, w = image.shape[:2]
    result_counts = {}
    with tempfile.TemporaryDirectory(prefix="traffic-doctor-") as folder:
        video = Path(folder) / "decode-test.mp4"
        out = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
        if not out.isOpened():
            raise ValueError("OpenCV MP4 encoder unavailable")
        for _ in range(2):
            out.write(image)
        out.release()
        for tracker in ("bytetrack", "botsort"):
            model = YOLO(str(model_path))
            cap = cv2.VideoCapture(str(video))
            frames = tracks = 0
            try:
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    result = model.track(frame, device=device, imgsz=640, persist=True,
                                         tracker=tracker + ".yaml", verbose=False)[0]
                    if result.boxes is not None and result.boxes.id is not None:
                        tracks += len(result.boxes.id)
                    frames += 1
                if frames != 2 or tracks <= 0:
                    raise ValueError(f"{tracker}: decoder/model/tracker check failed ({frames} frames, {tracks} tracked detections)")
                # Verify execution location, rather than relying only on CUDA discovery.
                executed_on = str(next(model.model.parameters()).device)
                if device not in ("cpu", "mps") and not executed_on.startswith("cuda"):
                    raise ValueError(f"GPU requested but model executed on {executed_on}")
                result_counts[tracker] = {"decoded_frames": frames, "tracked_detections": tracks,
                                          "model_device": executed_on}
            finally:
                cap.release()
    # Tk is needed for the VS Code file picker, not for the CLI analyzer.
    try:
        import tkinter
        picker_available = True
    except ImportError:
        picker_available = False
    return {"ready": True, "device": device, "model": str(model_path),
            "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            "torch_cuda": torch.version.cuda, "cuda_available": torch.cuda.is_available(),
            "gpu_name": torch.cuda.get_device_name(0) if device not in ("cpu", "mps") else None,
            "versions": {k: importlib.metadata.version(k) for k in ("traffic-los", "torch", "torchvision", "ultralytics", "opencv-python", "lap")},
            "file_picker_module_available": picker_available, "checks": result_counts}


def main():
    parser = argparse.ArgumentParser(description="Verify OpenCV decoding and real YOLO tracking on the requested device")
    parser.add_argument("--model", default="models/yolo11n.pt")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    # Invalidate a previous successful report before a fresh readiness check.
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"ready": False, "device": args.device}), encoding="utf-8")
    try:
        result = check(args.model, args.device)
        text = json.dumps(result, indent=2, ensure_ascii=False)
        if args.report:
            args.report.write_text(text, encoding="utf-8")
        print(text)
        print("OpenCV + YOLO + both trackers: PASS")
    except Exception as exc:
        parser.exit(1, f"Readiness check failed: {exc}\n")


if __name__ == "__main__":
    main()
