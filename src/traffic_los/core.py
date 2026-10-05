"""Geometry and event extraction independent of the detection backend."""
from collections import Counter
import math


def side(point, a, b):
    return (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])


def crosses(p, q, a, b):
    """Proper finite-segment intersection; exclude touches and collinear motion."""
    return side(p, a, b) * side(q, a, b) < 0 and side(a, p, q) * side(b, p, q) <= 0


def inside(point, polygon):
    x, y = point
    result = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            result = not result
        j = i
    return result


def validate(config):
    if config.get("schema_version") != 1:
        raise ValueError("scene schema_version must be 1")
    for dimension in ("width", "height"):
        if not isinstance(config.get(dimension), int) or config[dimension] <= 0:
            raise ValueError(f"positive integer {dimension} required")
    names = set()
    for item in config.get("lines", []) + config.get("zones", []):
        name = item.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("line/zone names must be nonempty and unique")
        names.add(name)
        points = item.get("points", [])
        if (item in config.get("lines", []) and len(points) != 2) or len(points) < 2:
            raise ValueError("lines require two points")
        if item in config.get("zones", []) and len(points) < 3:
            raise ValueError("zones require at least three points")
        for p in points:
            if len(p) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p):
                raise ValueError("coordinates must be finite numeric pairs")
            if not (0 <= p[0] <= config["width"] and 0 <= p[1] <= config["height"]):
                raise ValueError("coordinate outside reference image")
    for line in config.get("lines", []):
        if line["points"][0] == line["points"][1]:
            raise ValueError("zero-length line")
        if line.get("direction", "both") not in ("both", "positive", "negative"):
            raise ValueError("direction must be both, positive or negative")
        if line.get("role", "count") not in ("entry", "exit", "count"):
            raise ValueError("role must be entry, exit or count")
    if not config.get("lines") and not config.get("zones"):
        raise ValueError("annotate at least one line or zone before analysis")


class EventEngine:
    def __init__(self, config, deadband=3.0, max_gap=1.0, ttl=10.0):
        self.config = config
        self.deadband, self.max_gap, self.ttl = deadband, max_gap, ttl
        self.states = {}
        self.last_prune = 0.0
        self.roles = {line["name"]: line.get("role", "count") for line in config.get("lines", [])}

    def update(self, time, detections):
        events = []
        occupancy = Counter()
        for det in detections:
            tid, cls, p = det["id"], det["class"], det["point"]
            state = self.states.setdefault(tid, {"last": time, "lines": {}, "seen": set(), "entry": None, "moved": False})
            for zone in self.config.get("zones", []):
                if inside(p, zone["points"]):
                    occupancy[(zone["name"], cls)] += 1
            for line in self.config.get("lines", []):
                name = line["name"]
                if line.get("classes") and cls not in line["classes"]:
                    continue
                a, b = line["points"]
                s = side(p, a, b)
                distance = abs(s) / math.dist(a, b)
                if distance <= self.deadband:
                    continue
                prev = state["lines"].get(name)
                state["lines"][name] = (time, p, s)
                if not prev or name in state["seen"] or time - prev[0] > self.max_gap:
                    continue
                if not crosses(prev[1], p, a, b):
                    continue
                direction = "positive" if s > 0 else "negative"
                if line.get("direction", "both") not in ("both", direction):
                    continue
                # Interpolate the crossing time between bracketing observations.
                fraction = abs(prev[2]) / (abs(prev[2]) + abs(s))
                event_time = prev[0] + fraction * (time - prev[0])
                state["seen"].add(name)
                events.append({"kind": "crossing", "time_s": event_time, "track_id": tid,
                               "class": cls, "line": name, "direction": direction,
                               "entry": "", "exit": ""})
            state["last"] = time
        crossings = sorted(events, key=lambda e: e["time_s"])
        events = []
        for event in crossings:
            events.append(event)
            state = self.states[event["track_id"]]
            role = self.roles[event["line"]]
            if role == "entry" and state["entry"] is None:
                state["entry"] = (event["line"], event["time_s"])
            if role == "exit" and state["entry"] and not state["moved"]:
                entry, entry_time = state["entry"]
                if event["time_s"] > entry_time:
                    state["moved"] = True
                    events.append({**event, "kind": "movement", "line": "", "direction": "",
                                   "entry": entry, "exit": event["line"]})
        if time - self.last_prune >= self.ttl:
            self.states = {k: v for k, v in self.states.items() if time - v["last"] <= self.ttl}
            self.last_prune = time
        return events, occupancy
