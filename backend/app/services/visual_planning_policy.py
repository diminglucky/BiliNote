from typing import List


def screenshot_content_budget(items: List[object]) -> int:
    if not items:
        return 0
    total = 0
    for item in items:
        total += max(1, int(getattr(item, "suggested_count", 1)))
    return max(1, min(40, total))
