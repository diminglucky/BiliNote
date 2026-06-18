import re


TOC_HEADING_RE = re.compile(r"^(#{1,3})\s*目录\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _is_summary_heading(title: str) -> bool:
    compact = re.sub(r"\s+", "", title)
    return compact in {"AI总结", "总结"} or compact.startswith("AI总结")


def _strip_markdown_for_text(value: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\\", "")
    return text.strip()


def _normalize_content_marker_text(value: str) -> str:
    return re.sub(
        r"\*?Content-\[((?:\d{2}:)?\d{2}:\d{2})\]\*?",
        lambda match: f"*Content-[{match.group(1)}]*",
        value,
    )


def _clean_heading_title(raw_title: str) -> str:
    title = _strip_markdown_for_text(raw_title)
    title = re.sub(r"^\s*#+\s*", "", title).strip()
    return _normalize_content_marker_text(title)


def _github_style_anchor(title: str, used: dict[str, int]) -> str:
    text = _strip_markdown_for_text(title).lower()
    text = re.sub(r"[\*_~`]", "", text)
    text = re.sub(r"[!\"#$%&'()*+,./:;<=>?@\[\\\]^`{|}，。！？、；：“”‘’（）【】《》]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-{3,}", "--", text)
    slug = text or "section"
    count = used.get(slug, 0)
    used[slug] = count + 1
    if count:
        return f"{slug}-{count}"
    return slug


def _extract_toc_headings(markdown: str) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    in_fence = False

    for line in markdown.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        if level != 2:
            continue
        title = _clean_heading_title(match.group(2))
        if not title:
            continue
        if title == "目录" or _is_summary_heading(title):
            continue
        if "原片截图" in title:
            continue
        headings.append((level, title))

    return headings


def _find_toc_block(lines: list[str]) -> tuple[int, int] | None:
    in_fence = False
    for index, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not TOC_HEADING_RE.match(line.strip()):
            continue

        end = index + 1
        while end < len(lines):
            if HEADING_RE.match(lines[end]) and not TOC_HEADING_RE.match(lines[end].strip()):
                break
            end += 1

        while end > index + 1 and lines[end - 1].strip() in {"", "---", "***", "___"}:
            end -= 1
        return index, end

    return None


def _toc_insert_index(lines: list[str]) -> int:
    in_fence = False
    for index, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) == 2:
            return index
    return 0


def normalize_markdown_toc(markdown: str | None, ensure_toc: bool = False) -> str | None:
    """
    Rebuild the Markdown table of contents from real level-2 headings.

    LLMs often output `- [Title]` without the `(#anchor)` target, which looks
    like a TOC but cannot be clicked. This keeps the content structure
    deterministic instead of relying on the model to format links perfectly.
    """
    if markdown is None:
        return None
    if not markdown.strip():
        return markdown

    headings = _extract_toc_headings(markdown)
    if not headings:
        return markdown

    lines = markdown.splitlines()
    toc_block = _find_toc_block(lines)
    if not toc_block and not ensure_toc:
        return markdown

    used: dict[str, int] = {}
    toc_lines = ["## 目录", ""]
    for _level, title in headings:
        anchor = _github_style_anchor(title, used)
        toc_lines.append(f"- [{title}](#{anchor})")
    toc_lines.extend([""])

    if toc_block:
        start, end = toc_block
        new_lines = lines[:start] + toc_lines + lines[end:]
    else:
        insert_at = _toc_insert_index(lines)
        new_lines = lines[:insert_at] + toc_lines + lines[insert_at:]

    return "\n".join(new_lines).strip() + "\n"


def prepend_source_link(markdown: str | None, source_url: str) -> str | None:
    """
    在笔记开头添加来源链接；若首个非空行已包含来源链接，则更新该行并避免重复。
    """
    if markdown is None:
        return None

    source = (source_url or "").strip()
    if not source:
        return markdown

    header = f"> 来源链接：{source}"
    lines = markdown.splitlines()
    first_non_empty_idx = None
    for idx, line in enumerate(lines):
        if line.strip():
            first_non_empty_idx = idx
            break

    if first_non_empty_idx is not None:
        first_line = lines[first_non_empty_idx].strip()
        if first_line.startswith("> 来源链接：") or first_line.startswith("来源链接："):
            lines[first_non_empty_idx] = header
            return "\n".join(lines)

    if markdown.strip():
        return f"{header}\n\n{markdown}"
    return header


def replace_content_markers(markdown: str, video_id: str, platform: str = 'bilibili') -> str:
    """
    替换 *Content-04:16*、Content-04:16 或 Content-[04:16] 为超链接，跳转到对应平台视频的时间位置
    """
    # 匹配三种形式：*Content-04:16*、Content-04:16、Content-[04:16]
    pattern = r"\*?Content-(?:\[(\d{2}):(\d{2})\]|(\d{2}):(\d{2}))\*?"
    toc_marker_pattern = r"\*?Content-(?:\[((?:\d{2}:)?\d{2}:\d{2})\]|((?:\d{2}:)?\d{2}:\d{2}))\*?"

    safe_video_id = video_id

    def build_origin_link(mm: str, ss: str) -> str:
        total_seconds = int(mm) * 60 + int(ss)

        if platform == 'bilibili':
            parsed_video_id = safe_video_id.replace("_p", "?p=")
            url = f"https://www.bilibili.com/video/{parsed_video_id}&t={total_seconds}"
        elif platform == 'youtube':
            url = f"https://www.youtube.com/watch?v={safe_video_id}&t={total_seconds}s"
        elif platform == 'douyin':
            url = f"https://www.douyin.com/video/{safe_video_id}"
        else:
            return f"({mm}:{ss})"

        return f"[原片 @ {mm}:{ss}]({url})"

    def replace_line(line: str) -> str:
        stripped = line.lstrip()
        is_toc_link = bool(re.match(r"^[-*+]\s+\[", stripped))
        if is_toc_link:
            return re.sub(
                toc_marker_pattern,
                lambda match: f"*Content-[{match.group(1) or match.group(2)}]*",
                line,
            )

        def replacer(match):
            mm = match.group(1) or match.group(3)
            ss = match.group(2) or match.group(4)
            return build_origin_link(mm, ss)

        return re.sub(pattern, replacer, line)

    return "\n".join(replace_line(line) for line in markdown.splitlines())
