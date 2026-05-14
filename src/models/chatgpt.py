import asyncio
from typing import Optional, List, AsyncGenerator, Dict, Any

from chatgpt_web import ChatGPTClient


class MyChatGPTClient:
    """Async wrapper around the curl_cffi-based ChatGPT client."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.client: Optional[ChatGPTClient] = None

    async def init(self) -> None:
        """Initialize the sync client in a thread."""
        loop = asyncio.get_running_loop()
        self.client = await loop.run_in_executor(
            None, lambda: ChatGPTClient(access_token=self.access_token)
        )

    async def generate_content(
        self,
        message: str,
        model: str = "",
        files: Optional[List[str]] = None,
    ) -> str:
        """Non-streaming: send a message and return the full response."""
        if not self.client:
            raise RuntimeError("ChatGPT client not initialized")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.client.ask_blocking(message, model, files)
        )

    async def generate_stream(
        self,
        message: str,
        model: str = "",
        files: Optional[List[str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming: yield text chunks as they arrive."""
        if not self.client:
            raise RuntimeError("ChatGPT client not initialized")
        loop = asyncio.get_running_loop()

        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        def _produce():
            try:
                for chunk in self.client.ask(message, model):
                    if chunk:
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "type": "text",
                            "content": chunk,
                            "finish_reason": None,
                        })
                loop.call_soon_threadsafe(queue.put_nowait, {
                    "type": "text",
                    "content": "",
                    "finish_reason": "stop",
                })
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

    async def reset_conversation(self) -> None:
        """Reset (no-op for stateless anon endpoint)."""
        pass

    async def close(self) -> None:
        """Cleanup."""
        self.client = None
