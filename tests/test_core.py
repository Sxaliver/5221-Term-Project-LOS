import pytest
from traffic_los.core import EventEngine, crosses, inside, validate


def scene():
    return {"schema_version": 1, "width": 100, "height": 100,
            "lines": [{"name": "in", "role": "entry", "points": [[0, 20], [100, 20]]},
                      {"name": "out", "role": "exit", "points": [[0, 80], [100, 80]]}],
            "zones": [{"name": "area", "points": [[0, 0], [100, 0], [100, 100], [0, 100]]}]}


def det(y, tid=1, cls="car", x=50):
    return {"id": tid, "class": cls, "point": (x, y)}


def test_finite_segments_and_collinear_motion():
    assert crosses((5, -2), (5, 2), (0, 0), (10, 0))
    assert not crosses((15, -2), (15, 2), (0, 0), (10, 0))
    assert not crosses((2, 0), (5, 0), (0, 0), (10, 0))


def test_entry_exit_and_once_per_line_even_when_returning():
    engine = EventEngine(scene())
    engine.update(0, [det(10)])
    events, counts = engine.update(.2, [det(30)])
    assert len(events) == 1 and events[0]["line"] == "in"
    assert events[0]["time_s"] == pytest.approx(.1)
    assert counts[("area", "car")] == 1
    engine.update(.4, [det(70)])
    events, _ = engine.update(.6, [det(90)])
    assert [x["kind"] for x in events] == ["crossing", "movement"]
    assert events[1]["entry"] == "in" and events[1]["exit"] == "out"
    assert engine.update(.8, [det(10)])[0] == []


def test_deadband_keeps_bracketing_points_and_rejects_jitter():
    engine = EventEngine(scene(), deadband=3)
    engine.update(0, [det(10)])
    assert engine.update(.1, [det(19)])[0] == []
    assert engine.update(.2, [det(21)])[0] == []
    assert len(engine.update(.3, [det(30)])[0]) == 1


def test_same_frame_entry_exit_do_not_depend_on_annotation_order():
    config = scene()
    config["lines"].reverse()
    engine = EventEngine(config)
    engine.update(0, [det(10)])
    events, _ = engine.update(.5, [det(90)])
    assert [e["kind"] for e in events] == ["crossing", "crossing", "movement"]


def test_occlusion_gap_does_not_invent_crossing():
    engine = EventEngine(scene(), max_gap=1)
    engine.update(0, [det(10)])
    assert engine.update(5, [det(30)])[0] == []


def test_direction_and_class_filters():
    config = scene()
    config["lines"][0].update(direction="positive", classes=["car"])
    engine = EventEngine(config)
    engine.update(0, [det(30), det(10, 2, "person")])
    assert engine.update(.1, [det(10), det(30, 2, "person")])[0] == []


def test_expired_states_are_removed():
    engine = EventEngine(scene(), ttl=2)
    engine.update(0, [det(10)])
    engine.update(3, [])
    assert not engine.states


def test_polygon_and_validation():
    config = scene()
    validate(config)
    assert inside((20, 20), config["zones"][0]["points"])
    assert not inside((200, 20), config["zones"][0]["points"])
    config["lines"][0]["points"][0] = [float("nan"), 0]
    with pytest.raises(ValueError, match="finite"):
        validate(config)
