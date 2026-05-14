import json
import time
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.logger import logger
from app.services.chatgpt_client import get_chatgpt_client, ChatGPTClientNotInitializedError


class ChatGPTRequest(BaseModel):
    message: str
    model: str = Field(default="auto", description="Model: auto, gpt-4, gpt-4o, etc.")
    files: Optional[List[str]] = Field(default=None, description="File paths to upload (video/image)")
    stream: Optional[bool] = False


router = APIRouter()


def _truncate(msg: str, n: int = 60) -> str:
    return msg[:n] + "..." if len(msg) > n else msg


async def _call_gpt(client, message, model, files):
    """Call ChatGPT client with optional file uploads."""
    if files:
        return await client.generate_content(message, model=model, files=files)
    return await client.generate_content(message, model=model)


@router.post("/gpt")
async def gpt_generate(request: ChatGPTRequest):
    t0 = time.time()
    logger.info(f"[ChatGPT] POST /gpt model={request.model} msg=\"{_truncate(request.message)}\"")
    if request.files:
        logger.info(f"[ChatGPT] 附带 {len(request.files)} 个文件")

    try:
        client = get_chatgpt_client()
    except ChatGPTClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    await client.reset_conversation()

    try:
        response = await _call_gpt(client, request.message, request.model, request.files)
        elapsed = time.time() - t0
        logger.info(f"[ChatGPT] OK {len(response)} chars in {elapsed:.1f}s")
        return {"response": response}
    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[ChatGPT] ERROR after {elapsed:.1f}s: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/gpt-chat")
async def gpt_chat(request: ChatGPTRequest):
    t0 = time.time()
    logger.info(f"[ChatGPT] POST /gpt-chat model={request.model} msg=\"{_truncate(request.message)}\"")
    if request.files:
        logger.info(f"[ChatGPT] 附带 {len(request.files)} 个文件")

    try:
        client = get_chatgpt_client()
    except ChatGPTClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        response = await _call_gpt(client, request.message, request.model, request.files)
        elapsed = time.time() - t0
        logger.info(f"[ChatGPT] Chat OK {len(response)} chars in {elapsed:.1f}s")
        return {"response": response}
    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[ChatGPT] Chat ERROR after {elapsed:.1f}s: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/gpt/stream")
async def gpt_stream(request: ChatGPTRequest):
    t0 = time.time()
    logger.info(f"[ChatGPT] POST /gpt/stream model={request.model} msg=\"{_truncate(request.message)}\"")
    if request.files:
        logger.info(f"[ChatGPT] 附带 {len(request.files)} 个文件")

    try:
        client = get_chatgpt_client()
    except ChatGPTClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    await client.reset_conversation()

    async def event_stream():
        ts = int(time.time())
        chunk_id = f"chatcmpl-{ts}"
        total_chars = 0
        try:
            async for chunk in client.generate_stream(request.message, model=request.model, files=request.files):
                if chunk.get("type") != "text":
                    continue
                if chunk.get("finish_reason") == "stop":
                    sse_data = {
                        "id": chunk_id, "object": "chat.completion.chunk",
                        "created": ts, "model": request.model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                    yield f"data: {json.dumps(sse_data)}\n\n"
                    break
                content = chunk.get("content", "")
                if content:
                    total_chars += len(content)
                    sse_data = {
                        "id": chunk_id, "object": "chat.completion.chunk",
                        "created": ts, "model": request.model,
                        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(sse_data)}\n\n"
            yield "data: [DONE]\n\n"
            elapsed = time.time() - t0
            logger.info(f"[ChatGPT] Stream OK {total_chars} chars in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"[ChatGPT] Stream ERROR after {elapsed:.1f}s: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
