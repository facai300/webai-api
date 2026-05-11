import json
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.logger import logger
from app.services.chatgpt_client import get_chatgpt_client, ChatGPTClientNotInitializedError


class ChatGPTRequest(BaseModel):
    message: str
    model: str = Field(default="auto", description="Model: auto, gpt-4, gpt-4o, etc.")
    stream: Optional[bool] = False


router = APIRouter()


@router.post("/gpt")
async def gpt_generate(request: ChatGPTRequest):
    """Stateless generation with ChatGPT web."""
    try:
        client = get_chatgpt_client()
    except ChatGPTClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Reset conversation for stateless mode
    await client.reset_conversation()

    try:
        response = await client.generate_content(
            request.message,
            model=request.model,
        )
        return {"response": response}
    except Exception as e:
        logger.error(f"Error in /gpt endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/gpt-chat")
async def gpt_chat(request: ChatGPTRequest):
    """Stateful chat with ChatGPT, auto-maintains conversation context."""
    try:
        client = get_chatgpt_client()
    except ChatGPTClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        response = await client.generate_content(
            request.message,
            model=request.model,
        )
        return {"response": response}
    except Exception as e:
        logger.error(f"Error in /gpt-chat endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/gpt/stream")
async def gpt_stream(request: ChatGPTRequest):
    """Streaming generation with ChatGPT web (SSE, OpenAI compatible)."""
    try:
        client = get_chatgpt_client()
    except ChatGPTClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    await client.reset_conversation()

    async def event_stream():
        import time
        ts = int(time.time())
        chunk_id = f"chatcmpl-{ts}"
        try:
            async for chunk in client.generate_stream(
                request.message,
                model=request.model,
            ):
                if chunk.get("type") != "text":
                    continue
                if chunk.get("finish_reason") == "stop":
                    sse_data = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": ts,
                        "model": request.model,
                        "choices": [{
                            "index": 0, "delta": {}, "finish_reason": "stop",
                        }],
                    }
                    yield f"data: {json.dumps(sse_data)}\n\n"
                    break
                content = chunk.get("content", "")
                if content:
                    sse_data = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": ts,
                        "model": request.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": content},
                            "finish_reason": None,
                        }],
                    }
                    yield f"data: {json.dumps(sse_data)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Error in /gpt/stream: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
