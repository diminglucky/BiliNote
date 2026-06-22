import os
import pathlib
import sys
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / ".test_tmp" / "proxy"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.services.proxy_config_manager import ProxyConfigManager


class TestProxyConfigManager(unittest.TestCase):
    def _config_path(self, name: str) -> pathlib.Path:
        TMP_ROOT.mkdir(exist_ok=True)
        path = TMP_ROOT / f"{name}.json"
        if path.exists():
            path.unlink()
        return path

    def test_env_proxy_is_ignored_by_default(self):
        manager = ProxyConfigManager(str(self._config_path("ignored_by_default")))

        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9"}, clear=True):
            self.assertIsNone(manager.get_proxy_url())

    def test_standard_env_proxy_is_ignored_even_with_old_opt_in_flag(self):
        manager = ProxyConfigManager(str(self._config_path("standard_env_ignored")))

        with patch.dict(
            os.environ,
            {
                "VIDEONOTE_USE_ENV_PROXY": "1",
                "HTTPS_PROXY": "http://127.0.0.1:7890",
            },
            clear=True,
        ):
            self.assertIsNone(manager.get_proxy_url())

    def test_dedicated_env_proxy_is_supported(self):
        manager = ProxyConfigManager(str(self._config_path("dedicated_env")))

        with patch.dict(os.environ, {"VIDEONOTE_PROXY_URL": "http://127.0.0.1:7890"}, clear=True):
            self.assertEqual(manager.get_proxy_url(), "http://127.0.0.1:7890")

    def test_configured_proxy_wins_over_env_proxy(self):
        manager = ProxyConfigManager(str(self._config_path("configured_wins")))
        manager.update_config(True, "http://127.0.0.1:7890")

        with patch.dict(
            os.environ,
            {
                    "VIDEONOTE_PROXY_URL": "http://127.0.0.1:7891",
                    "HTTPS_PROXY": "http://127.0.0.1:9",
                },
                clear=True,
            ):
            self.assertEqual(manager.get_proxy_url(), "http://127.0.0.1:7890")

    def test_invalid_configured_proxy_is_ignored(self):
        manager = ProxyConfigManager(str(self._config_path("invalid_ignored")))
        manager.update_config(True, "127.0.0.1:7890")

        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(manager.get_proxy_url())


if __name__ == "__main__":
    unittest.main()
