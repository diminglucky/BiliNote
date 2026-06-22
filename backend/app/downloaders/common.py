import logging

from app.services.proxy_config_manager import ProxyConfigManager


logger = logging.getLogger(__name__)


def apply_yt_dlp_proxy(ydl_opts: dict, label: str = "yt-dlp") -> dict:
    """Apply VideoNote's explicit proxy policy to yt-dlp options.

    yt-dlp can inherit HTTP_PROXY/HTTPS_PROXY from the process environment.
    For this app that is too surprising: a stale local proxy can break every
    video download. Use the UI-configured proxy when enabled; otherwise force
    a direct connection with an empty proxy string.
    """
    proxy = ProxyConfigManager().get_proxy_url()
    ydl_opts["proxy"] = proxy or ""
    if proxy:
        logger.info("%s 走代理: %s", label, proxy)
    return ydl_opts
