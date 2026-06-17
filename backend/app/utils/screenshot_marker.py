import re
from typing import List, Tuple


def normalize_screenshot_markers(markdown: str) -> str:
    grouped_pattern = r"\*?Screenshots-((?:\[\d{2}:\d{2}\][ \t]*,?[ \t]*)+)\*?"

    def replace_group(match: re.Match) -> str:
        times = re.findall(r"\[(\d{2}):(\d{2})\]", match.group(1))
        if not times:
            return match.group(0)
        return "\n".join(f"*Screenshot-[{mm}:{ss}]" for mm, ss in times)

    return re.sub(grouped_pattern, replace_group, markdown)


def extract_screenshot_timestamps(markdown: str) -> List[Tuple[str, int]]:
    markdown = normalize_screenshot_markers(markdown)
    pattern = r"(\*?Screenshot-(?:\[(\d{2}):(\d{2})\]|(\d{2}):(\d{2}))\*?)"
    results: List[Tuple[str, int]] = []
    for match in re.finditer(pattern, markdown):
        mm = match.group(2) or match.group(4)
        ss = match.group(3) or match.group(5)
        total_seconds = int(mm) * 60 + int(ss)
        results.append((match.group(1), total_seconds))
    return results
