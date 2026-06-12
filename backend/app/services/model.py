from app.db.model_dao import insert_model, get_all_models, get_model_by_provider_and_name, delete_model
from app.enmus.exception import ProviderErrorEnum
from app.exceptions.provider import ProviderError
from app.gpt.gpt_factory import GPTFactory
from app.gpt.provider.OpenAI_compatible_provider import OpenAICompatibleProvider
from app.models.model_config import ModelConfig
from app.services.provider import ProviderService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ModelService:
    @staticmethod
    def _build_model_config(provider: dict) -> ModelConfig:
        return ModelConfig(
            api_key=provider["api_key"],
            base_url=provider["base_url"],
            provider=provider["name"],
            model_name="",
            name=provider["name"],
        )

    @staticmethod
    def _model_base_url_candidates(base_url: str) -> list[str]:
        normalized = (base_url or "").rstrip("/")
        if not normalized:
            return [normalized]

        candidates = [normalized]
        if not normalized.endswith("/v1") and "/v1/" not in normalized:
            candidates.append(f"{normalized}/v1")
        return candidates

    @staticmethod
    def _serialize_model(model) -> dict:
        if isinstance(model, dict):
            data = dict(model)
        elif isinstance(model, str):
            data = {"id": model}
        elif hasattr(model, "model_dump"):
            data = model.model_dump()
        elif hasattr(model, "dict"):
            data = model.dict()
        else:
            data = {"id": str(model)}

        model_id = data.get("id") or data.get("name") or str(model)
        return {
            "id": model_id,
            "created": data.get("created", 0),
            "object": data.get("object", "model"),
            "owned_by": data.get("owned_by", ""),
        }

    @staticmethod
    def _serialize_model_response(models) -> list[dict]:
        if isinstance(models, dict):
            raw_models = models.get("data") or models.get("models") or []
        else:
            raw_models = getattr(models, "data", models)

        if raw_models is None:
            return []
        return [ModelService._serialize_model(model) for model in raw_models]

    @staticmethod
    def get_model_list(provider_id: int | str, verbose: bool = False):
        provider = ProviderService.get_provider_by_id(provider_id)
        if not provider:
            raise ValueError("provider not found")

        last_error = None
        for base_url in ModelService._model_base_url_candidates(provider.get("base_url", "")):
            candidate_provider = {**provider, "base_url": base_url}
            try:
                config = ModelService._build_model_config(candidate_provider)
                gpt = GPTFactory().from_config(config)
                models = gpt.list_models()
                if verbose:
                    logger.info(f"[{provider['name']}] model list loaded from {base_url}: {models}")
                if base_url != provider.get("base_url"):
                    logger.info(f"[{provider['name']}] model list loaded with fallback base_url: {base_url}")
                return models
            except Exception as e:
                last_error = e
                logger.warning(f"[{provider['name']}] failed to load models from {base_url}: {e}")

        raise RuntimeError(f"failed to load provider model list: {last_error}")

    @staticmethod
    def get_all_models(verbose: bool = False):
        try:
            raw_models = get_all_models()
            if verbose:
                logger.info(f"all enabled models: {raw_models}")
            return ModelService._format_models(raw_models)
        except Exception as e:
            logger.error(f"failed to load all models: {e}")
            return []

    @staticmethod
    def get_all_models_safe(verbose: bool = False):
        return ModelService.get_all_models(verbose=verbose)

    @staticmethod
    def _format_models(raw_models: list) -> list:
        formatted = []
        for model in raw_models:
            formatted.append({
                "id": model.get("id"),
                "provider_id": model.get("provider_id"),
                "model_name": model.get("model_name"),
                "created_at": model.get("created_at", None),
            })
        return formatted

    @staticmethod
    def get_enabled_models_by_provider(provider_id: str | int):
        from app.db.model_dao import get_models_by_provider

        return get_models_by_provider(provider_id)

    @staticmethod
    def get_all_models_by_id(provider_id: str, verbose: bool = False):
        provider = ProviderService.get_provider_by_id(provider_id)
        if not provider:
            raise ValueError("provider not found")

        models = ModelService.get_model_list(provider["id"], verbose=verbose)
        model_list = {
            "models": ModelService._serialize_model_response(models),
        }

        logger.info(f"[{provider['name']}] loaded model list successfully")
        return model_list

    @staticmethod
    def connect_test(id: str, model: str | None = None) -> bool:
        provider = ProviderService.get_provider_by_id(id)
        if not provider:
            raise ProviderError(
                code=ProviderErrorEnum.NOT_FOUND.code,
                message=ProviderErrorEnum.NOT_FOUND.message,
            )
        if not provider.get("api_key"):
            raise ProviderError(
                code=ProviderErrorEnum.NOT_FOUND.code,
                message=ProviderErrorEnum.NOT_FOUND.message,
            )

        if not model:
            saved_models = ModelService.get_enabled_models_by_provider(provider["id"])
            if not saved_models:
                raise ProviderError(
                    code=ProviderErrorEnum.WRONG_PARAMETER.code,
                    message="请先为该供应商添加至少一个模型再测试连通性",
                )
            model = saved_models[0]["model_name"]

        ok = OpenAICompatibleProvider.test_connection(
            api_key=provider.get("api_key"),
            base_url=provider.get("base_url"),
            model=model,
        )
        if ok:
            return True
        raise ProviderError(
            code=ProviderErrorEnum.WRONG_PARAMETER.code,
            message=ProviderErrorEnum.WRONG_PARAMETER.message,
        )

    @staticmethod
    def delete_model_by_id(model_id: int) -> bool:
        try:
            delete_model(model_id)
            return True
        except Exception as e:
            logger.error(f"[{model_id}] failed to delete model: {e}")
            return False

    @staticmethod
    def add_new_model(provider_id: int | str, model_name: str) -> bool:
        try:
            provider = ProviderService.get_provider_by_id(provider_id)
            if not provider:
                logger.error(f"provider {provider_id} not found; cannot add model")
                return False

            existing = get_model_by_provider_and_name(provider_id, model_name)
            if existing:
                logger.info(f"model {model_name} already exists for provider {provider_id}")
                return False

            insert_model(provider_id=provider_id, model_name=model_name)
            logger.info(f"model {model_name} added to provider {provider_id}")
            return True
        except Exception as e:
            logger.error(f"failed to add model: {e}")
            return False


if __name__ == "__main__":
    print(ModelService.get_model_list(1, verbose=True))
