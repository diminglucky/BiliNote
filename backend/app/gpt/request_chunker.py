from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class ChunkPayload:
    segments: list
    image_urls: list


class RequestChunker:
    def __init__(
        self,
        message_builder: Callable,
        max_bytes: int,
        size_estimator: Optional[Callable] = None,
        max_images_per_chunk: int = 5,
    ):
        self.message_builder = message_builder
        self.max_bytes = max_bytes
        self.size_estimator = size_estimator
        self.max_images_per_chunk = max_images_per_chunk

    def estimate(self, messages) -> int:
        if self.size_estimator:
            return self.size_estimator(messages)
        import json
        return len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))

    def _messages_size(self, segments, image_urls, **kwargs) -> int:
        messages = self.message_builder(segments, image_urls, **kwargs)
        return self.estimate(messages)

    def _get_text(self, segment) -> str:
        if isinstance(segment, dict):
            return segment.get("text", "")
        return getattr(segment, "text", "")

    def _get_start(self, item) -> float:
        if isinstance(item, dict):
            return float(item.get("start", 0) or 0)
        return float(getattr(item, "start", 0) or 0)

    def _get_end(self, item) -> float:
        if isinstance(item, dict):
            return float(item.get("end", self._get_start(item)) or self._get_start(item))
        return float(getattr(item, "end", self._get_start(item)) or self._get_start(item))

    def _chunk_time_range(self, chunk: ChunkPayload) -> tuple[float, float]:
        if not chunk.segments:
            return 0, 0
        return self._get_start(chunk.segments[0]), self._get_end(chunk.segments[-1])

    def _image_url(self, image):
        if isinstance(image, dict):
            return image.get("url", "")
        return image

    def _make_segment(self, segment, text: str):
        if isinstance(segment, dict):
            new_seg = dict(segment)
            new_seg["text"] = text
            return new_seg
        if hasattr(segment, "__dict__"):
            data = dict(segment.__dict__)
            data["text"] = text
            return type(segment)(**data)
        return type(segment)(segment.start, segment.end, text)

    def _split_segment_to_fit(self, segment, **kwargs):
        text = self._get_text(segment)
        if not text:
            raise ValueError("empty segment cannot be split")
        lo, hi = 1, len(text)
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = self._make_segment(segment, text[:mid])
            size = self._messages_size([candidate], [], **kwargs)
            if size <= self.max_bytes:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best is None:
            raise ValueError("single segment too large to fit request")
        head = self._make_segment(segment, text[:best])
        tail = self._make_segment(segment, text[best:])
        return head, tail

    def chunk(self, segments: list, image_urls: list, **kwargs) -> List[ChunkPayload]:
        segments = list(segments or [])
        raw_images = list(image_urls or [])
        if not segments and not raw_images:
            return []

        chunks: List[ChunkPayload] = []
        seg_idx = 0

        while seg_idx < len(segments):
            batch_segments = []
            while seg_idx < len(segments):
                candidate = batch_segments + [segments[seg_idx]]
                size = self._messages_size(candidate, [], **kwargs)
                if size <= self.max_bytes:
                    batch_segments = candidate
                    seg_idx += 1
                    continue
                if not batch_segments:
                    head, tail = self._split_segment_to_fit(segments[seg_idx], **kwargs)
                    segments[seg_idx] = head
                    segments.insert(seg_idx + 1, tail)
                    continue
                break

            if not batch_segments:
                raise ValueError("unable to fit any content into chunk")

            chunks.append(ChunkPayload(segments=batch_segments, image_urls=[]))

        if not raw_images:
            return chunks

        if not chunks:
            chunks = [ChunkPayload(segments=[], image_urls=[])]

        if not segments:
            for image in raw_images:
                appended = False
                for chunk in chunks[-1:]:
                    candidate_images = chunk.image_urls + [image]
                    if len(candidate_images) > self.max_images_per_chunk:
                        continue
                    if self._messages_size(chunk.segments, candidate_images, **kwargs) <= self.max_bytes:
                        chunk.image_urls = candidate_images
                        appended = True
                        break

                if appended:
                    continue

                if self._messages_size([], [image], **kwargs) > self.max_bytes:
                    raise ValueError("single image payload exceeds max_bytes")
                chunks.append(ChunkPayload(segments=[], image_urls=[image]))
            return chunks

        for idx, image in enumerate(raw_images):
            preferred_idx = self._preferred_chunk_index(chunks, image, idx, len(raw_images))
            placed = False

            for chunk_idx in range(preferred_idx, len(chunks)):
                chunk = chunks[chunk_idx]
                candidate_images = chunk.image_urls + [image]
                if len(candidate_images) > self.max_images_per_chunk:
                    continue
                if self._messages_size(chunk.segments, candidate_images, **kwargs) <= self.max_bytes:
                    chunk.image_urls = candidate_images
                    placed = True
                    break

            if placed:
                continue

            if self._messages_size([], [image], **kwargs) > self.max_bytes:
                # 单张图片过大时跳过这一张，而不是把整次视频理解降级为纯文本。
                continue
            chunks.append(ChunkPayload(segments=[], image_urls=[image]))

        return chunks

    def _preferred_chunk_index(self, chunks: List[ChunkPayload], image, image_idx: int, total_images: int) -> int:
        if not chunks:
            return 0

        if isinstance(image, dict):
            image_start = float(image.get("start", 0) or 0)
            image_end = float(image.get("end", image_start) or image_start)
            image_mid = (image_start + image_end) / 2
            best_idx = 0
            best_distance = float("inf")
            for idx, chunk in enumerate(chunks):
                chunk_start, chunk_end = self._chunk_time_range(chunk)
                if chunk_start <= image_mid <= chunk_end:
                    return idx
                if image_mid < chunk_start:
                    distance = chunk_start - image_mid
                else:
                    distance = image_mid - chunk_end
                if distance < best_distance:
                    best_idx = idx
                    best_distance = distance
            return best_idx

        return min(len(chunks) - 1, (image_idx * len(chunks)) // max(total_images, 1))

    def group_texts_by_budget(self, texts: List[str], build_messages: Callable, **kwargs) -> List[List[str]]:
        groups: List[List[str]] = []
        idx = 0
        while idx < len(texts):
            group: List[str] = []
            while idx < len(texts):
                candidate = group + [texts[idx]]
                try:
                    messages = build_messages(candidate, [], **kwargs)
                except TypeError:
                    messages = build_messages(candidate, **kwargs)
                size = self.estimate(messages)
                if size <= self.max_bytes:
                    group = candidate
                    idx += 1
                    continue
                if not group:
                    raise ValueError("single text block exceeds max_bytes")
                break
            groups.append(group)
        return groups
