import asyncio
from typing import Optional, AsyncGenerator, Dict, Any

from deepseek_web import DeepSeekAPI

_SENTINEL = object()

MODEL_MAP = {
    "deepseek-chat": {"thinking": False, "search": False},
    "deepseek-v3": {"thinking": False, "search": False},
    "deepseek-reasoner": {"thinking": True, "search": False},
    "deepseek-r1": {"thinking": True, "search": False},
    "deepseek-chat-search": {"thinking": False, "search": True},
    "deepseek-v3-search": {"thinking": False, "search": True},
    "deepseek-reasoner-search": {"thinking": True, "search": True},
    "deepseek-r1-search": {"thinking": True, "search": True},
}

def _resolve_model(model: str) -> dict:
    """Resolve model name to thinking/search flags."""
    resolved = MODEL_MAP.get(model)
    if not resolved:
        resolved = {"thinking": False, "search": False}
    return resolved


class MyDeepSeekClient:
    """Async wrapper around the sync DeepSeekAPI client."""

    def __init__(self, auth_token: str):
        self.auth_token = auth_token
        self.client: Optional[DeepSeekAPI] = None

    async def init(self) -> None:
        """Initialize the sync DeepSeekAPI client in a thread."""
        loop = asyncio.get_running_loop()
        self.client = await loop.run_in_executor(None, DeepSeekAPI, self.auth_token)

    async def generate_content(
        self,
        message: str,
        model: str = "deepseek-chat",
        thinking_enabled: Optional[bool] = None,
        search_enabled: Optional[bool] = None,
    ) -> str:
        """Non-streaming: send a message and collect all text chunks."""
        if not self.client:
            raise RuntimeError("DeepSeek client not initialized")
        flags = _resolve_model(model)
        if thinking_enabled is not None:
            flags["thinking"] = thinking_enabled
        if search_enabled is not None:
            flags["search"] = search_enabled

        loop = asyncio.get_running_loop()

        chat_id = await loop.run_in_executor(None, self.client.create_chat_session)

        generator = self.client.chat_completion(
            chat_id,
            message,
            thinking_enabled=flags["thinking"],
            search_enabled=flags["search"],
        )

        text_parts = []
        for chunk in await loop.run_in_executor(None, lambda: list(generator)):
            if chunk.get("type") == "text":
                text_parts.append(chunk.get("content", ""))

        return "".join(text_parts)

    async def generate_stream(
        self,
        message: str,
        model: str = "deepseek-chat",
        thinking_enabled: Optional[bool] = None,
        search_enabled: Optional[bool] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming: yield chunks as they arrive from the sync generator."""
        if not self.client:
            raise RuntimeError("DeepSeek client not initialized")
        flags = _resolve_model(model)
        if thinking_enabled is not None:
            flags["thinking"] = thinking_enabled
        if search_enabled is not None:
            flags["search"] = search_enabled

        loop = asyncio.get_running_loop()

        chat_id = await loop.run_in_executor(None, self.client.create_chat_session)

        generator = self.client.chat_completion(
            chat_id,
            message,
            thinking_enabled=flags["thinking"],
            search_enabled=flags["search"],
        )

        queue: asyncio.Queue = asyncio.Queue()

        def _produce():
            try:
                for chunk in generator:
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        loop.run_in_executor(None, _produce)

        while True:
            chunk = await queue.get()
            if chunk is _SENTINEL:
                break
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    async def close(self) -> None:
        """Cleanup."""
        self.client = None
