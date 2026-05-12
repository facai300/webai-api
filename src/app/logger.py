# src/app/logger.py
import logging

# Suppress noisy third-party library logs
for noisy in ("revChatGPT", "gemini_webapi", "curl_cffi", "httpx", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("app")
