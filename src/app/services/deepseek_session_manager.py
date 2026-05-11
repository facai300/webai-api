import asyncio
from typing import Optional, Dict, Any, AsyncGenerator

from app.logger import logger
from app.services.deepseek_client import get_deepseek_client, DeepSeekClientNotInitializedError


class DeepSeekSessionManager:
    """Manages a persistent DeepSeek chat session with context."""

    def __init__(self, client):
        self.client = client
        self.chat_session_id: Optional[str] = None
        self.parent_message_id: Optional[str] = None
        self.lock = asyncio.Lock()

    async def get_response(
        self,
        message: str,
        model: str = "deepseek-chat",
        thinking_enabled: Optional[bool] = None,
        search_enabled: Optional[bool] = None,
    ) -> str:
        """Send a message in the session and return the full text response."""
        async with self.lock:
            loop = asyncio.get_running_loop()

            # Create session on first message
            if self.chat_session_id is None:
                self.chat_session_id = await loop.run_in_executor(
                    None, self.client.client.create_chat_session
                )

            # Determine flags
            from models.deepseek import _resolve_model
            flags = _resolve_model(model)
            if thinking_enabled is not None:
                flags["thinking"] = thinking_enabled
            if search_enabled is not None:
                flags["search"] = search_enabled

            generator = self.client.client.chat_completion(
                self.chat_session_id,
                message,
                parent_message_id=self.parent_message_id,
                thinking_enabled=flags["thinking"],
                search_enabled=flags["search"],
            )

            text_parts = []
            last_message_id = None
            for chunk in await loop.run_in_executor(None, lambda: list(generator)):
                if chunk.get("type") == "text":
                    text_parts.append(chunk.get("content", ""))
                if chunk.get("type") == "message_id":
                    last_message_id = chunk.get("content")

            if last_message_id:
                self.parent_message_id = last_message_id

            return "".join(text_parts)


_deepseek_chat_manager = None


def init_deepseek_session_managers():
    """Initialize the DeepSeek chat session manager."""
    global _deepseek_chat_manager
    try:
        client = get_deepseek_client()
        _deepseek_chat_manager = DeepSeekSessionManager(client)
    except DeepSeekClientNotInitializedError:
        logger.warning("DeepSeek session manager not initialized: client not available.")


def get_deepseek_chat_manager():
    return _deepseek_chat_manager
