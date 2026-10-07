"""Run with system Python to prepare an isolated local VS Code environment."""
import argparse
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def cuda_index(output, compute_capability=None):
    # Recent NVIDIA-SMI versions label this field "CUDA UMD Version".
    match = re.search(r"\bCUDA(?:\s+UMD)?\s+Version\s*:\s*(\d+)\.(\d+)\b", output, re.IGNORECASE)
    if not match:
        raise ValueError("nvidia-smi did not report a recognized CUDA version field; inspect its full output to distinguish a parsing issue from unavailable CUDA")
    version = tuple(map(int, match.groups()))
    # CUDA 12.8 PyTorch wheels drop support for some older architectures.
    # Prefer CUDA 12.6 for legacy hardware and still require real inference.
    legacy = compute_capability is not None and compute_capability < 7.5
    if version >= (12, 8) and not legacy:
        return "cu128"
    if version >= (12, 6):
        return "cu126"
    raise ValueError("This pinned PyTorch setup needs driver CUDA support >=12.6. Update the NVIDIA driver, or explicitly choose --accelerator cpu.")


def detect_nvidia():
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        raise ValueError("nvidia-smi failed; check that the NVIDIA driver and GPU are available")
    probe = subprocess.run(["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"], capture_output=True, text=True, check=False)
    capability = None
    if probe.returncode == 0:
        first = probe.stdout.strip().splitlines()
        if first and re.fullmatch(r"\d+\.\d+", first[0].strip()):
            capability = float(first[0].strip())
    return cuda_index(result.stdout, capability)


def run(command):
    print("Running:", " ".join(map(str, command)), flush=True)
    subprocess.run([str(x) for x in command], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description="Install isolated dependencies, download YOLO, and verify CPU/GPU inference")
    parser.add_argument("--accelerator", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv")
    args = parser.parse_args()
    if not (3, 10) <= sys.version_info[:2] < (3, 14):
        parser.exit(1, "Use Python 3.12 (supported installer range: 3.10–3.13).\n")
    try:
        state = ROOT / ".local"
        state.mkdir(exist_ok=True)
        (state / "deployment.json").write_text(json.dumps({"ready": False}), encoding="utf-8")
        index = None if args.accelerator == "cpu" else detect_nvidia()
        if args.accelerator == "cuda" and index is None:
            raise ValueError("NVIDIA GPU/driver not detected by nvidia-smi; install/check the driver and retry")
        device = "0" if index else "cpu"
        environment = args.venv.resolve()
        if environment.exists() and not (environment / "pyvenv.cfg").is_file():
            raise ValueError(f"Refusing to modify a non-venv directory: {environment}")
        if not environment.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
        if not python.is_file():
            raise ValueError(f"Virtual environment has no usable Python: {python}")
        packages = [python, "-m", "pip", "install", "torch==2.9.0", "torchvision==0.24.0"]
        if index:
            packages += ["--index-url", f"https://download.pytorch.org/whl/{index}"]
        elif platform.system() != "Darwin":
            packages += ["--index-url", "https://download.pytorch.org/whl/cpu"]
        run(packages)
        # An existing CPU build can satisfy an unqualified version constraint.
        # Switch wheels explicitly when their installed backend differs.
        if index or platform.system() != "Darwin":
            probe = subprocess.run([str(python), "-c", "import torch; print(torch.version.cuda or '')"], capture_output=True, text=True, check=True)
            expected = {"cu126": "12.6", "cu128": "12.8"}.get(index, "")
            if probe.stdout.strip() != expected:
                run(packages + ["--force-reinstall"])
        run([python, "-m", "pip", "install", "-e", ".[test]"])
        run([python, "-m", "pip", "check"])
        run([python, "-m", "pytest", "-q"])
        model = ROOT / "models" / "yolo11n.pt"
        model.parent.mkdir(exist_ok=True)
        # Success is recorded only after actual inference and tracking pass.
        run([python, "-m", "traffic_los.doctor", "--model", model, "--device", device,
             "--report", state / "deployment.json"])
        report = json.loads((state / "deployment.json").read_text(encoding="utf-8"))
        print(f"READY: device={report['device']}; model={model}", flush=True)
        if not report["file_picker_module_available"]:
            print("tkinter is missing: CLI analysis is ready, but install tkinter or pass explicit --video/--scene paths to use the launcher.")
        print("VS Code: Terminal > Run Task > Traffic: Annotate video, then Traffic: Pilot (2 min).")
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Deployment failed: {exc}\nNo successful deployment is claimed.\n")


if __name__ == "__main__":
    main()
