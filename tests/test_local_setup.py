import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("version, expected", [("12.6", "cu126"), ("12.8", "cu128"), ("13.0", "cu128")])
def test_cuda_wheel_selection(version, expected):
    bootstrap = load_tool("bootstrap_local")
    assert bootstrap.cuda_index(f"CUDA Version: {version}") == expected


@pytest.mark.parametrize("header", [
    "NVIDIA-SMI 616.92    KMD Version: 616.92    CUDA UMD Version: 13.4",
    "CUDA UMD Version : 13.4",
    "cuda version: 12.8",
])
def test_new_nvidia_smi_header_selects_supported_pytorch_wheel(header):
    bootstrap = load_tool("bootstrap_local")
    assert bootstrap.cuda_index(header, compute_capability=8.6) == "cu128"


def test_cuda_legacy_architecture_and_old_driver():
    bootstrap = load_tool("bootstrap_local")
    assert bootstrap.cuda_index("CUDA Version: 12.8", compute_capability=6.1) == "cu126"
    with pytest.raises(ValueError, match="driver CUDA support"):
        bootstrap.cuda_index("CUDA Version: 12.4")
    with pytest.raises(ValueError, match="did not report"):
        bootstrap.cuda_index("CUDA Version: N/A")


def test_video_launcher_uses_separate_pilot_and_full_outputs(tmp_path):
    launcher = load_tool("run_video")
    video = tmp_path / "video with spaces.MPG"
    scene = tmp_path / "scene with spaces.json"
    command, output = launcher.build_command("pilot", video, scene, "0")
    assert str(video) in command and str(scene) in command
    assert command[command.index("--device") + 1] == "0"
    assert command[command.index("--duration") + 1] == "120"
    assert output.name.startswith("vscode-pilot-")
    command, output = launcher.build_command("full", video, scene, "0")
    assert "--duration" not in command and "--resume" in command
    assert output.name == "vscode-full"


def test_vscode_tasks_use_venv_interpreter():
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text())
    for task in tasks["tasks"]:
        if "Deploy" not in task["label"]:
            assert ".venv" in task["windows"]["command"]
        assert task["type"] == "process"


def test_doctor_invalidates_old_success_on_failure(tmp_path, monkeypatch):
    from traffic_los import doctor
    report = tmp_path / "deployment.json"
    report.write_text(json.dumps({"ready": True}))
    def fail(*args):
        raise ValueError("GPU unavailable")
    monkeypatch.setattr(doctor, "check", fail)
    monkeypatch.setattr("sys.argv", ["doctor", "--report", str(report), "--device", "0"])
    with pytest.raises(SystemExit) as exc:
        doctor.main()
    assert exc.value.code == 1
    assert json.loads(report.read_text())["ready"] is False


def test_bootstrap_missing_gpu_cannot_reuse_stale_success(tmp_path, monkeypatch):
    bootstrap = load_tool("bootstrap_local")
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "detect_nvidia", lambda: None)
    monkeypatch.setattr("sys.argv", ["bootstrap_local", "--accelerator", "cuda"])
    state = tmp_path / ".local"
    state.mkdir()
    (state / "deployment.json").write_text(json.dumps({"ready": True}))
    with pytest.raises(SystemExit) as exc:
        bootstrap.main()
    assert exc.value.code == 1
    assert not json.loads((state / "deployment.json").read_text())["ready"]
