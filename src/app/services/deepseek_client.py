from models.deepseek import MyDeepSeekClient
from app.config import CONFIG
from app.logger import logger


class DeepSeekClientNotInitializedError(Exception):
    """Raised when the DeepSeek client is not initialized."""
    pass


_deepseek_client = None
_initialization_error = None


async def init_deepseek_client() -> bool:
    """Initialize the DeepSeek client from configuration."""
    global _deepseek_client, _initialization_error
    _initialization_error = None

    if CONFIG.getboolean("EnabledAI", "deepseek", fallback=True):
        try:
            # 1. Try config first
            auth_token = CONFIG["DeepSeek"].get("auth_token", "").strip()

            # 2. Auto-extract from browser if not in config
            if not auth_token:
                logger.info("No DeepSeek token in config, trying browser extraction...")
                try:
                    from app.utils.browser import get_deepseek_token_from_browser
                    auth_token = get_deepseek_token_from_browser() or ""
                    if auth_token:
                        logger.info("DeepSeek token auto-extracted from browser.")
                        # Save to in-memory config and persist to disk
                        CONFIG["DeepSeek"]["auth_token"] = auth_token
                        try:
                            with open("config.conf", "w", encoding="utf-8") as f:
                                CONFIG.write(f)
                            logger.info("DeepSeek token saved to config.conf.")
                        except Exception as e:
                            logger.warning(f"Failed to persist token to config.conf: {e}")
                except Exception as e:
                    logger.warning(f"Browser extraction failed: {e}")

            if not auth_token:
                error_msg = (
                    "DeepSeek auth_token not found. "
                    "Please log in to chat.deepseek.com in your browser, "
                    "or manually add the token to [DeepSeek] auth_token in config.conf "
                    "(get it from DevTools -> Application -> Local Storage -> userToken)."
                )
                logger.error(error_msg)
                _initialization_error = error_msg
                return False

            _deepseek_client = MyDeepSeekClient(auth_token)
            await _deepseek_client.init()
            logger.info("DeepSeek client initialized successfully.")
            return True

        except Exception as e:
            error_msg = f"Unexpected error initializing DeepSeek client: {e}"
            logger.error(error_msg, exc_info=True)
            _deepseek_client = None
            _initialization_error = error_msg
            return False
    else:
        error_msg = "DeepSeek client is disabled in config."
        logger.info(error_msg)
        _initialization_error = error_msg
        return False


def get_deepseek_client():
    """Return the initialized DeepSeek client instance."""
    if _deepseek_client is None:
        error_detail = (
            _initialization_error
            or "DeepSeek client was not initialized. Check logs for details."
        )
        raise DeepSeekClientNotInitializedError(error_detail)
    return _deepseek_client
