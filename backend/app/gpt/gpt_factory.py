from openai import OpenAI

from app.gpt.base import GPT
from app.gpt.provider.OpenAI_compatible_provider import OpenAICompatibleProvider
from app.gpt.universal_gpt import UniversalGPT
from app.models.model_config import ModelConfig


class GPTFactory:
    @staticmethod
    def from_config(config: ModelConfig) -> GPT:
        client = OpenAICompatibleProvider(api_key=config.api_key, base_url=config.base_url).get_client
        provider_name = (config.name or "").lower()
        model_name = (config.model_name or "").lower()
        supports_vision = GPTFactory._supports_vision(provider_name, model_name)
        return UniversalGPT(client=client, model=config.model_name, supports_vision=supports_vision)

    @staticmethod
    def _supports_vision(provider_name: str, model_name: str) -> bool:
        # 不按供应商粗暴判断，避免 qwen/deepseek 的纯文本模型收到 image_url 后报错。
        vision_tokens = (
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
        non_vision_tokens = (
            "deepseek",
            "text",
            "embedding",
            "whisper",
            "tts",
        )
        if any(token in model_name for token in non_vision_tokens):
            return False
        return any(token in model_name for token in vision_tokens)
