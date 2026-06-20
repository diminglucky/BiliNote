import os
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from app.services.visual_planning_policy import screenshot_content_budget


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        return default
    return max(minimum, min(maximum, value))


@dataclass
class VisualScreenshotSlot:
    slot_id: int
    mode: str
    timestamp: int
    index: int
    marker: Optional[str] = None
    plan: Optional[Any] = None


class VisualSlotPlanner:
    """Builds executable screenshot slots from explicit markers and visual plans."""

    def __init__(
        self,
        matching_visual_plan: Callable[[int, List[Any]], Optional[Any]],
        slot_cls: type = VisualScreenshotSlot,
    ):
        self.matching_visual_plan = matching_visual_plan
        self.slot_cls = slot_cls

    def plan(
        self,
        matches: List[Tuple[str, int]],
        visual_plans: List[Any],
    ) -> List[Any]:
        slots: List[Any] = []
        selected_plan_starts: set[int] = set()

        for idx, (marker, ts) in enumerate(matches):
            plan = self.matching_visual_plan(ts, visual_plans)
            if plan:
                selected_plan_starts.add(plan.start)
            slots.append(self.slot_cls(
                slot_id=len(slots),
                mode="marker",
                timestamp=ts,
                index=idx,
                marker=marker,
                plan=plan,
            ))

        supplement_limit = _env_int(
            "SCREENSHOT_SUPPLEMENT_LIMIT",
            screenshot_content_budget(visual_plans),
            0,
            40,
        )
        if supplement_limit > 0:
            missing_plans = [plan for plan in visual_plans if plan.start not in selected_plan_starts]
            missing_plans = sorted(missing_plans, key=lambda item: (-item.score, item.start))[:supplement_limit]
            missing_plans.sort(key=lambda item: item.start)
            for offset, plan in enumerate(missing_plans):
                slots.append(self.slot_cls(
                    slot_id=len(slots),
                    mode="fallback",
                    timestamp=plan.start,
                    index=len(matches) + offset,
                    plan=plan,
                ))

        return slots
