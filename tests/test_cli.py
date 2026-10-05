import csv
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from traffic_los.cli import analyze, annotate, export


class Array:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class FakeModel:
    names = {0: "car"}
    ckpt_path = None

    def __init__(self, *args):
        self.frame = 0

    def track(self, frame, **kwargs):
        y = 10 + self.frame * 10
        self.frame += 1
        boxes = SimpleNamespace(xyxy=Array([[45, y - 5, 55, y]]), id=Array([1]), cls=Array([0]), conf=Array([.9]))
        return [SimpleNamespace(boxes=boxes)]


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    import ultralytics
    monkeypatch.setattr(ultralytics, "YOLO", FakeModel)
    path = tmp_path / "video.mp4"
    output = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (100, 100))
    assert output.isOpened()
    for _ in range(10):
        output.write(np.zeros((100, 100, 3), dtype=np.uint8))
    output.release()
    scene = tmp_path / "scene.json"
    scene.write_text(json.dumps({"schema_version": 1, "width": 100, "height": 100,
         "lines": [{"name": "in", "role": "entry", "points": [[0, 20], [100, 20]]},
                   {"name": "out", "role": "exit", "points": [[0, 80], [100, 80]]}],
         "zones": [{"name": "area", "points": [[0, 0], [100, 0], [100, 100], [0, 100]]}]}))
    return SimpleNamespace(inputs=[str(path)], scene=str(scene), output=str(tmp_path / "runs"),
              model="fake.pt", tracker="bytetrack", conf=.25, imgsz=640, classes=["car"],
              bin_seconds=.5, deadband=3, max_gap=1, track_sample_seconds=.1, device="cpu",
              resume=False, duration=None, overlay_seconds=0)


def test_streaming_outputs_bins_and_file_resume(prepared):
    analyze(prepared)
    result = next(p for p in Path(prepared.output).iterdir() if p.is_dir())
    metadata = json.loads((result / "metadata.json").read_text())
    assert metadata["complete"] and metadata["decoded_frames"] == 10
    with (result / "events.csv").open() as f:
        events = list(csv.DictReader(f))
    assert [e["kind"] for e in events] == ["crossing", "crossing", "movement"]
    with (result / "summary.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert sum(int(r["count"]) for r in rows if r["kind"] == "movement") == 1
    assert any(int(r["count"]) == 0 for r in rows)
    before = (result / "events.csv").stat().st_mtime_ns
    prepared.resume = True
    analyze(prepared)
    assert (result / "events.csv").stat().st_mtime_ns == before
    prepared.conf = .3
    with pytest.raises(ValueError, match="settings changed"):
        analyze(prepared)


def test_duration_limit_and_interrupted_output_preservation(prepared):
    prepared.duration = .5
    analyze(prepared)
    result = next(Path(prepared.output).iterdir())
    metadata = json.loads((result / "metadata.json").read_text())
    assert metadata["decoded_frames"] == 5 and metadata["termination"] == "duration_limit"
    partial = result.with_name(f".{result.name}.partial")
    result.rename(partial)
    analyze(prepared)
    assert (result / "metadata.json").exists()
    backups = list(Path(prepared.output).glob("*.interrupted-*"))
    assert len(backups) == 1 and (backups[0] / "events.csv").exists()


def test_annotation_page_uses_source_dimensions(prepared, tmp_path):
    args = SimpleNamespace(video=prepared.inputs[0], at=0, output=str(tmp_path / "annotator.html"))
    annotate(args)
    page = Path(args.output).read_text()
    assert 'width="100" height="100"' in page and "data:image/jpeg;base64," in page
    assert "scene.json" in page
    with pytest.raises(ValueError, match="overwrite"):
        annotate(args)


def test_export_only_completed_summaries(prepared, tmp_path):
    analyze(prepared)
    destination = tmp_path / "results"
    args = SimpleNamespace(run=prepared.output, output=str(destination))
    export(args)
    result = next(destination.iterdir())
    assert (result / "summary.csv").exists() and not (result / "tracks.csv").exists()
    meta = json.loads((result / "metadata.json").read_text())
    assert meta["settings"]["source"] == "video.mp4"
    with pytest.raises(ValueError, match="overwrite"):
        export(args)
