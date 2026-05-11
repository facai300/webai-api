import json
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.logger import logger
from app.services.deepseek_client import get_deepseek_client, DeepSeekClientNotInitializedError
from app.services.deepseek_session_manager import get_deepseek_chat_manager


class DeepSeekRequest(BaseModel):
    message: str
    model: str = Field(default="deepseek-chat", description="Model: deepseek-chat, deepseek-reasoner, deepseek-v3, deepseek-r1")
    thinking_enabled: Optional[bool] = None
    search_enabled: Optional[bool] = None
    stream: Optional[bool] = False


router = APIRouter()


@router.post("/deepseek")
async def deepseek_generate(request: DeepSeekRequest):
    """Stateless content generation with DeepSeek."""
    try:
        client = get_deepseek_client()
    except DeepSeekClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        response = await client.generate_content(
            request.message,
            model=request.model,
            thinking_enabled=request.thinking_enabled,
            search_enabled=request.search_enabled,
        )
        return {"response": response}
    except Exception as e:
        logger.error(f"Error in /deepseek endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating content: {str(e)}")


@router.post("/deepseek-chat")
async def deepseek_chat(request: DeepSeekRequest):
    """Stateful chat with DeepSeek, maintaining conversation context."""
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
        return {"response": response}
    except Exception as e:
        logger.error(f"Error in /deepseek-chat endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error in chat: {str(e)}")


@router.post("/deepseek/stream")
async def deepseek_stream(request: DeepSeekRequest):
    """Streaming content generation with DeepSeek (SSE)."""
    try:
        client = get_deepseek_client()
    except DeepSeekClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    async def event_stream():
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
                    # OpenAI-compatible SSE format for streaming
                    sse_data = {
                        "choices": [{"delta": {"content": content}, "index": 0}]
                    }
                    yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Error in /deepseek/stream: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
