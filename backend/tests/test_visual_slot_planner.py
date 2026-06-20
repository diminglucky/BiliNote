import pathlib
import sys
from dataclasses import dataclass


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.visual_slot_planner import VisualSlotPlanner, screenshot_content_budget


@dataclass
class _Plan:
    start: int
    end: int = 0
    score: float = 1.0
    suggested_count: int = 1


def _matching_plan(timestamp, plans):
    for plan in plans:
        if plan.start <= timestamp < (plan.end or plan.start + 30):
            return plan
    return None


def test_slot_planner_keeps_explicit_markers_and_attaches_matching_plan():
    plans = [_Plan(start=10, end=40, score=4.0)]
    planner = VisualSlotPlanner(_matching_plan)

    slots = planner.plan([("*Screenshot-[00:15]", 15)], plans)

    assert len(slots) == 1
    assert slots[0].mode == "marker"
    assert slots[0].timestamp == 15
    assert slots[0].marker == "*Screenshot-[00:15]"
    assert slots[0].plan is plans[0]


def test_slot_planner_adds_unmatched_document_plans_as_fallbacks_in_time_order():
    plans = [
        _Plan(start=90, end=120, score=5.0),
        _Plan(start=10, end=30, score=3.0),
        _Plan(start=50, end=80, score=4.0),
    ]
    planner = VisualSlotPlanner(_matching_plan)

    slots = planner.plan([], plans)

    assert [slot.mode for slot in slots] == ["fallback", "fallback", "fallback"]
    assert [slot.timestamp for slot in slots] == [10, 50, 90]
    assert [slot.slot_id for slot in slots] == [0, 1, 2]
    assert [slot.index for slot in slots] == [0, 1, 2]


def test_slot_planner_does_not_duplicate_plan_already_claimed_by_marker():
    plans = [
        _Plan(start=10, end=40, score=4.0),
        _Plan(start=80, end=110, score=5.0),
    ]
    planner = VisualSlotPlanner(_matching_plan)

    slots = planner.plan([("*Screenshot-[00:20]", 20)], plans)

    assert [slot.mode for slot in slots] == ["marker", "fallback"]
    assert [slot.timestamp for slot in slots] == [20, 80]
    assert slots[0].plan is plans[0]
    assert slots[1].plan is plans[1]


def test_slot_planner_respects_supplement_limit_from_environment(monkeypatch):
    monkeypatch.setenv("SCREENSHOT_SUPPLEMENT_LIMIT", "1")
    plans = [
        _Plan(start=10, end=30, score=1.0),
        _Plan(start=40, end=60, score=5.0),
        _Plan(start=80, end=100, score=3.0),
    ]
    planner = VisualSlotPlanner(_matching_plan)

    slots = planner.plan([], plans)

    assert len(slots) == 1
    assert slots[0].mode == "fallback"
    assert slots[0].timestamp == 40
    assert slots[0].plan is plans[1]


def test_screenshot_content_budget_is_based_on_requested_visual_density():
    assert screenshot_content_budget([]) == 0
    assert screenshot_content_budget([_Plan(start=0, suggested_count=0)]) == 1
    assert screenshot_content_budget(
        [_Plan(start=idx, suggested_count=2) for idx in range(50)]
    ) == 40
