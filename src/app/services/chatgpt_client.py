from models.chatgpt import MyChatGPTClient
from app.config import CONFIG
from app.logger import logger


class ChatGPTClientNotInitializedError(Exception):
    """Raised when the ChatGPT client is not initialized."""
    pass


_chatgpt_client = None
_initialization_error = None


async def init_chatgpt_client() -> bool:
    """Initialize the ChatGPT client from configuration."""
    global _chatgpt_client, _initialization_error
    _initialization_error = None

    enabled = CONFIG.getboolean("EnabledAI", "chatgpt", fallback=False)
    if not enabled:
        _initialization_error = "ChatGPT client is disabled in config."
        logger.info(_initialization_error)
        return False

    try:
        access_token = CONFIG["ChatGPT"].get("access_token", "").strip()
        base_url = CONFIG["ChatGPT"].get("base_url", "").strip()

        if not access_token:
            error_msg = (
                "ChatGPT access_token not found in config.conf. "
                "Open https://chat.openai.com in your browser, open DevTools, "
                "go to Application → Cookies → __Secure-next-auth.session-token, "
                "or check https://chat.openai.com/api/auth/session for access_token."
            )
            logger.error(error_msg)
            _initialization_error = error_msg
            return False

        _chatgpt_client = MyChatGPTClient(access_token)
        await _chatgpt_client.init()
        logger.info("ChatGPT client initialized successfully.")
        return True

    except Exception as e:
        error_msg = f"Unexpected error initializing ChatGPT client: {e}"
        logger.error(error_msg, exc_info=True)
        _chatgpt_client = None
        _initialization_error = error_msg
        return False


def get_chatgpt_client():
    """Return the initialized ChatGPT client instance."""
    if _chatgpt_client is None:
        error_detail = (
            _initialization_error
            or "ChatGPT client was not initialized. Check logs for details."
        )
        raise ChatGPTClientNotInitializedError(error_detail)
    return _chatgpt_client
