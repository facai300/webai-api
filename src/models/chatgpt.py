import asyncio
from typing import Optional, AsyncGenerator, Dict, Any

from revChatGPT.V1 import Chatbot


class MyChatGPTClient:
    """Async wrapper around revChatGPT V1 Chatbot."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.chatbot: Optional[Chatbot] = None

    async def init(self) -> None:
        """Initialize the sync Chatbot in a thread."""
        loop = asyncio.get_running_loop()
        self.chatbot = await loop.run_in_executor(
            None,
            lambda: Chatbot(config={"access_token": self.access_token}),
        )

    async def generate_content(
        self,
        message: str,
        model: str = "auto",
    ) -> str:
        """Non-streaming: send a message and collect the full response."""
        if not self.chatbot:
            raise RuntimeError("ChatGPT client not initialized")

        loop = asyncio.get_running_loop()
        generator = self.chatbot.ask(
            prompt=message,
            model=model,
        )

        full_text = []
        for chunk in await loop.run_in_executor(None, lambda: list(generator)):
            content = chunk.get("message", "")
            if content:
                full_text.append(content)

        return "".join(full_text)

    async def generate_stream(
        self,
        message: str,
        model: str = "auto",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming: yield text chunks as they arrive."""
        if not self.chatbot:
            raise RuntimeError("ChatGPT client not initialized")

        loop = asyncio.get_running_loop()
        generator = self.chatbot.ask(
            prompt=message,
            model=model,
        )

        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        def _produce():
            try:
                prev_text = ""
                for chunk in generator:
                    full_text = chunk.get("message", "")
                    delta = full_text[len(prev_text):]
                    prev_text = full_text
                    if delta:
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "type": "text",
                            "content": delta,
                            "finish_reason": None,
                        })
                    conversation_id = chunk.get("conversation_id")
                    parent_id = chunk.get("parent_id")
                    if conversation_id and parent_id:
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "type": "message_id",
                            "content": f"{conversation_id}:{parent_id}",
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
        """Reset the current conversation (starts fresh on next ask)."""
        if self.chatbot:
            self.chatbot.conversation_id = None
            self.chatbot.parent_id = None
            self.chatbot.conversation_mapping = {}

    async def close(self) -> None:
        """Cleanup."""
        self.chatbot = None
