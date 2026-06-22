import os
import pathlib
import sys
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / ".test_tmp" / "proxy"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.downloaders.common import apply_yt_dlp_proxy
from app.services.proxy_config_manager import ProxyConfigManager


class TestDownloaderProxyPolicy(unittest.TestCase):
    def _config_path(self, name: str) -> pathlib.Path:
        TMP_ROOT.mkdir(exist_ok=True)
        path = TMP_ROOT / f"{name}.json"
        if path.exists():
            path.unlink()
        return path

    def test_yt_dlp_proxy_is_forced_direct_when_env_proxy_is_not_opted_in(self):
        manager = ProxyConfigManager(str(self._config_path("yt_dlp_direct")))

        with (
            patch("app.downloaders.common.ProxyConfigManager", return_value=manager),
            patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:9"}, clear=True),
        ):
            opts = apply_yt_dlp_proxy({})

        self.assertEqual(opts["proxy"], "")

    def test_yt_dlp_proxy_uses_configured_proxy(self):
        manager = ProxyConfigManager(str(self._config_path("yt_dlp_configured")))
        manager.update_config(True, "http://127.0.0.1:7890")

        with (
            patch("app.downloaders.common.ProxyConfigManager", return_value=manager),
            patch.dict(
                os.environ,
                {
                    "VIDEONOTE_PROXY_URL": "http://127.0.0.1:7891",
                    "HTTPS_PROXY": "http://127.0.0.1:9",
                },
                clear=True,
            ),
        ):
            opts = apply_yt_dlp_proxy({})

        self.assertEqual(opts["proxy"], "http://127.0.0.1:7890")


if __name__ == "__main__":
    unittest.main()
