import json
import time
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.logger import logger
from app.services.deepseek_client import get_deepseek_client, DeepSeekClientNotInitializedError
from app.services.deepseek_session_manager import get_deepseek_chat_manager


class DeepSeekRequest(BaseModel):
    message: str
    model: str = Field(default="deepseek-v3", description="Model: deepseek-v3, deepseek-r1")
    thinking_enabled: Optional[bool] = None
    search_enabled: Optional[bool] = None
    stream: Optional[bool] = False


router = APIRouter()


def _truncate(msg: str, n: int = 60) -> str:
    return msg[:n] + "..." if len(msg) > n else msg


@router.post("/deepseek")
async def deepseek_generate(request: DeepSeekRequest):
    """Stateless content generation with DeepSeek."""
    t0 = time.time()
    logger.info(f"[DeepSeek] POST /deepseek model={request.model} msg=\"{_truncate(request.message)}\"")

    try:
        client = get_deepseek_client()
    except DeepSeekClientNotInitializedError as e:
        logger.warning(f"[DeepSeek] Client not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e))

    try:
        response = await client.generate_content(
            request.message,
            model=request.model,
            thinking_enabled=request.thinking_enabled,
            search_enabled=request.search_enabled,
        )
        elapsed = time.time() - t0
        logger.info(f"[DeepSeek] OK model={request.model} {len(response)} chars in {elapsed:.1f}s")
        return {"response": response}
    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[DeepSeek] ERROR model={request.model} after {elapsed:.1f}s: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating content: {str(e)}")


@router.post("/deepseek-chat")
async def deepseek_chat(request: DeepSeekRequest):
    """Stateful chat with DeepSeek, maintaining conversation context."""
    t0 = time.time()
    logger.info(f"[DeepSeek] POST /deepseek-chat model={request.model} msg=\"{_truncate(request.message)}\"")

    try:
        get_deepseek_client()
    except DeepSeekClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    session_manager = get_deepseek_chat_manager()
    if not session_manager:
        raise HTTPException(status_code=503, detail="DeepSeek session manager is not initialized.")

    try:
        response = await session_manager.get_response(
            request.message,
            model=request.model,
            thinking_enabled=request.thinking_enabled,
            search_enabled=request.search_enabled,
        )
        elapsed = time.time() - t0
        logger.info(f"[DeepSeek] Chat OK model={request.model} {len(response)} chars in {elapsed:.1f}s")
        return {"response": response}
    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[DeepSeek] Chat ERROR model={request.model} after {elapsed:.1f}s: {e}")
        raise HTTPException(status_code=500, detail=f"Error in chat: {str(e)}")


@router.post("/deepseek/stream")
async def deepseek_stream(request: DeepSeekRequest):
    """Streaming content generation with DeepSeek (SSE)."""
    t0 = time.time()
    logger.info(f"[DeepSeek] POST /deepseek/stream model={request.model} msg=\"{_truncate(request.message)}\"")

    try:
        client = get_deepseek_client()
    except DeepSeekClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    async def event_stream():
        total_chars = 0
        try:
            async for chunk in client.generate_stream(
                request.message,
                model=request.model,
                thinking_enabled=request.thinking_enabled,
                search_enabled=request.search_enabled,
            ):
                if chunk.get("type") not in ("text", "thinking"):
                    continue
                if chunk.get("finish_reason") == "stop":
                    break
                content = chunk.get("content", "")
                if content:
                    total_chars += len(content)
                    sse_data = {
                        "choices": [{"delta": {"content": content}, "index": 0}]
                    }
                    yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            elapsed = time.time() - t0
            logger.info(f"[DeepSeek] Stream OK model={request.model} {total_chars} chars in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"[DeepSeek] Stream ERROR after {elapsed:.1f}s: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
