import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse


class ProxyConfigManager:
    """全局代理配置，存 JSON 文件，支持前端动态修改。

    作用范围：LLM API + 转写 API（Groq 等）+ yt-dlp 视频下载。
    优先级：配置文件里 enabled=true 的 url > 专用环境变量 VIDEONOTE_PROXY_URL。

    不读取通用 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY，避免本机、IDE 或运行沙箱里的
    代理变量污染视频下载流程。
    """

    def __init__(self, filepath: str = "config/proxy.json"):
        self.path = Path(filepath)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write(self, data: Dict[str, Any]):
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_config(self) -> Dict[str, Any]:
        data = self._read()
        return {
            "enabled": bool(data.get("enabled", False)),
            "url": data.get("url", "") or "",
        }

    @staticmethod
    def _is_valid_proxy_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https", "socks5", "socks5h"} and bool(parsed.netloc)

    def update_config(self, enabled: bool, url: Optional[str] = None) -> Dict[str, Any]:
        data = self._read()
        data["enabled"] = bool(enabled)
        if url is not None:
            data["url"] = url.strip()
        self._write(data)
        return self.get_config()

    def get_proxy_url(self) -> Optional[str]:
        """返回当前生效的代理 URL；没有则 None。

        - 配置文件 enabled=true 且 url 非空 → 用配置的 url。
        - 否则只读取专用环境变量 VIDEONOTE_PROXY_URL。

        这样可以避免本机/IDE/测试环境里的坏代理污染视频下载流程，例如
        http://127.0.0.1:9 这种不可达代理会让 B 站接口直接失败。
        """
        cfg = self.get_config()
        if cfg["enabled"] and cfg["url"] and self._is_valid_proxy_url(cfg["url"]):
            return cfg["url"]
        env_proxy = os.environ.get("VIDEONOTE_PROXY_URL", "").strip()
        if env_proxy and self._is_valid_proxy_url(env_proxy):
            return env_proxy
        return None
