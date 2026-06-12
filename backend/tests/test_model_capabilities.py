import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_model_capabilities():
    module_path = ROOT / "app" / "gpt" / "model_capabilities.py"
    spec = importlib.util.spec_from_file_location("model_capabilities", module_path)
    if spec is None or spec.loader is None:
        raise ImportError("model_capabilities module spec not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


infer_model_capabilities = _load_model_capabilities().infer_model_capabilities


class TestModelCapabilities(unittest.TestCase):
    def test_vision_models_are_detected(self):
        for model_name in ("gpt-4o", "qwen2.5-vl-72b-instruct", "gemini-1.5-pro"):
            with self.subTest(model_name=model_name):
                self.assertTrue(infer_model_capabilities("provider", model_name).supports_vision)

    def test_text_models_are_not_detected_as_vision(self):
        for model_name in ("deepseek-chat", "text-embedding-3-small", "whisper-large-v3"):
            with self.subTest(model_name=model_name):
                self.assertFalse(infer_model_capabilities("provider", model_name).supports_vision)


if __name__ == "__main__":
    unittest.main()
