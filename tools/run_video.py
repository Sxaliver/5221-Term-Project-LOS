"""Native file picker launcher for VS Code; analysis uses the CLI pipeline."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def build_command(mode, video, scene=None, device="cpu", model=None):
    video = Path(video).resolve()
    if mode == "annotate":
        stamp = time.time_ns()
        output = ROOT / ".local" / f"annotation-{stamp}.html"
        return [sys.executable, "-m", "traffic_los.cli", "annotate", str(video),
                "--output", str(output)], output
    if scene is None:
        raise ValueError("Select the scene JSON downloaded from your own video annotation")
    output = ROOT / "runs" / (f"vscode-pilot-{time.time_ns()}" if mode == "pilot" else "vscode-full")
    command = [sys.executable, "-m", "traffic_los.cli", "analyze", str(video), "--scene", str(Path(scene).resolve()),
               "--model", str(model or ROOT / "models" / "yolo11n.pt"), "--device", device,
               "--output", str(output), "--resume", "--overlay-seconds", "120"]
    if mode == "pilot":
        command += ["--duration", "120"]
    return command, output


def select_file(title, types, directory):
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise ValueError("File picker requires tkinter (included in the standard Windows Python installer); alternatively pass --video and --scene") from exc
    app = tk.Tk()
    app.withdraw()
    app.attributes("-topmost", True)
    try:
        return filedialog.askopenfilename(parent=app, title=title, initialdir=str(directory), filetypes=types)
    finally:
        app.destroy()


def main():
    parser = argparse.ArgumentParser(description="Select a local video and annotate or analyze it")
    parser.add_argument("--mode", choices=["annotate", "pilot", "full"], required=True)
    parser.add_argument("--video", type=Path, help="optional explicit path instead of a file picker")
    parser.add_argument("--scene", type=Path, help="optional explicit JSON path instead of a file picker")
    parser.add_argument("--device", help="override the device verified during deployment")
    args = parser.parse_args()
    try:
        video = args.video or select_file("选择交通视频 / Select video", [("Video", "*.MPG *.mpg *.mpeg *.mp4 *.avi *.mov *.mkv"), ("All files", "*.*")], ROOT / "data")
        if not video:
            print("Cancelled; no video processed.")
            return
        scene = None
        device = args.device or "cpu"
        model = ROOT / "models" / "yolo11n.pt"
        if args.mode != "annotate":
            state = ROOT / ".local" / "deployment.json"
            if not state.exists():
                raise ValueError("Run the VS Code deployment task first (missing deployment.json)")
            report = json.loads(state.read_text(encoding="utf-8"))
            if not report.get("ready"):
                raise ValueError("Deployment self-check did not pass; rerun deployment")
            device = args.device or report["device"]
            model = Path(report["model"])
            if not model.is_file():
                raise ValueError("Verified model file missing; rerun deployment")
            scene = args.scene or select_file("选择标注配置 / Select scene JSON", [("Scene JSON", "*.json")], ROOT / "configs")
            if not scene:
                print("Cancelled; no video processed.")
                return
        command, output = build_command(args.mode, video, scene, device, model)
        print("Running:", " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
        if args.mode == "annotate":
            opened = webbrowser.open(output.resolve().as_uri())
            if not opened:
                print(f"Open this file in your browser: {output}")
            print("Draw counting lines/regions; download scene.json to configs/. Then run the Pilot task.")
        else:
            print(f"Done. Inspect CSV files and overlay.mp4 in {output}")
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Launch failed: {exc}\n")


if __name__ == "__main__":
    main()
