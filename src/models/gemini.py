import configparser
import logging
import os
from typing import Optional, List, Union
from pathlib import Path
from gemini_webapi import GeminiClient as WebGeminiClient
from gemini_webapi.exceptions import APIError
from app.config import CONFIG

logger = logging.getLogger("app")

# Maps user-facing short names to the internal model identifiers accepted by gemini-webapi.
MODEL_ALIASES = {
    "flash":    "gemini-3-flash",
    "thinking": "gemini-3-flash-thinking",
    "pro":      "gemini-3-pro",
}

def resolve_model_name(model: str) -> str:
    """Resolve a model name alias to its internal identifier."""
    return MODEL_ALIASES.get(model, model)

class MyGeminiClient:
    """
    Wrapper for the Gemini Web API client.
    """
    def __init__(self, secure_1psid: str, secure_1psidts: str, proxy: str | None = None) -> None:
        self.client = WebGeminiClient(secure_1psid, secure_1psidts, proxy)
        self.client.auto_refresh = False
        self._gems_cache = None

    async def init(self) -> None:
        """Initialize the Gemini client and persist any rotated cookies."""
        await self.client.init(
            auto_refresh=False, auto_close=False,
            timeout=600, watchdog_timeout=300,
        )
        self.client.auto_refresh = False
        # 直接 pin _running: close() 后立即复位
        self._orig_client_close = self.client.close
        async def _close_pin(delay=0):
            await self._orig_client_close(delay)
            self.client._running = True
        self.client.close = _close_pin
        await self._persist_cookies()

    async def _persist_cookies(self) -> None:
        """不再回写 cookie 到 config.conf，避免被 Google 标记的 cookie 覆盖好的。
        Gemini 每次启动都从 Firefox 提取最新 cookie。"""
        pass  # disabled - always use fresh Firefox cookies

    async def generate_content(
        self,
        message: str,
        model: str,
        files: Optional[List[Union[str, Path]]] = None,
        gem: Optional[str] = None,
    ):
        """
        Generate content using the Gemini client.
        On 1100 error, force-reinit the client and retry once.
        """
        import asyncio
        resolved_model = resolve_model_name(model)
        resolved_gem = await self._resolve_gem(gem) if gem else None

        for attempt in range(3):
            try:
                if attempt > 0:
                    logger.info(f"[Gemini] 1100 重试 ({attempt}/2)，重新初始化客户端...")
                    # Force reinit: close old client, create new one
                    await self.client.close()
                    self.client = WebGeminiClient(
                        self.client._cookies.get("__Secure-1PSID", ""),
                        self.client._cookies.get("__Secure-1PSIDTS", ""),
                        self.client.proxy,
                    )
                    self.client.auto_refresh = False
                    await self.client.init(auto_refresh=False, auto_close=False)
                    self.client.auto_refresh = False
                    await asyncio.sleep(5)

                return await self.client.generate_content(
                    message, model=resolved_model, files=files, gem=resolved_gem
                )
            except APIError as e:
                err_str = str(e)
                if "1100" in err_str and attempt < 2:
                    continue
                raise

        raise RuntimeError("Gemini generate_content failed after retries")

    async def fetch_gems(self):
        """Fetch available gems and cache them."""
        self._gems_cache = await self.client.fetch_gems()
        return self._gems_cache

    async def _resolve_gem(self, gem_id_or_name: str):
        """Resolve a gem by ID or name."""
        if self._gems_cache is None:
            await self.fetch_gems()
        for gem in self._gems_cache:
            if gem.id == gem_id_or_name or gem.name.lower() == gem_id_or_name.lower():
                return gem
        return gem_id_or_name

    async def close(self) -> None:
        """Close the Gemini client."""
        await self.client.close()

    def start_chat(self, model: str, gem: Optional[str] = None):
        """
        Start a chat session with the given model.
        """
        resolved_model = resolve_model_name(model)
        # Note: Gem resolution might need to be async if we want to support name resolution here
        # For now, we'll assume gem is passed as ID or already resolved if possible
        # but the underlying library might expect a Gem object.
        return self.client.start_chat(model=resolved_model, gem=gem)
