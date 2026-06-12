from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapabilities:
    supports_vision: bool = False


VISION_MODEL_TOKENS = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-4-vision",
    "o4",
    "gemini",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qvq",
    "vision",
    "vl",
)

NON_VISION_MODEL_TOKENS = (
    "deepseek",
    "text",
    "embedding",
    "whisper",
    "tts",
)


def infer_model_capabilities(provider_name: str = "", model_name: str = "") -> ModelCapabilities:
    normalized_model = (model_name or "").lower()
    if any(token in normalized_model for token in NON_VISION_MODEL_TOKENS):
        return ModelCapabilities(supports_vision=False)
    return ModelCapabilities(
        supports_vision=any(token in normalized_model for token in VISION_MODEL_TOKENS),
    )
