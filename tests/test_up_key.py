from test_local_setup import load_tool


def event(action, injected=False):
    return {"action": action, "injected": injected}


def test_up_key_capture_distinguishes_repeat_and_release():
    tool = load_tool("diagnose_up_key")
    held = tool.summarize([event("down"), event("down"), event("down")])
    assert held["repeated_down_without_release"] == 2 and held["last_event_state_down"]
    released = tool.summarize([event("down"), event("down"), event("up")])
    assert not released["last_event_state_down"] and released["up_events"] == 1
    assert "normal while a key is held" in released["finding"]


def test_up_key_injection_is_evidence_not_process_attribution():
    tool = load_tool("diagnose_up_key")
    summary = tool.summarize([event("down", True), event("up", True)])
    assert summary["injected_events"] == 2
    assert "does not identify" in summary["finding"]
    assert tool.summarize([])["down_events"] == 0
    assert "does not establish" in tool.summarize([])["finding"]
