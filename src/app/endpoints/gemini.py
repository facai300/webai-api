import time
from fastapi import APIRouter, HTTPException
from app.logger import logger
from schemas.request import GeminiRequest
from app.services.gemini_client import get_gemini_client, GeminiClientNotInitializedError
from app.services.session_manager import get_gemini_chat_manager

from pathlib import Path
from typing import Union, List, Optional

router = APIRouter()


def _truncate(msg: str, n: int = 60) -> str:
    return msg[:n] + "..." if len(msg) > n else msg


@router.post("/gemini")
async def gemini_generate(request: GeminiRequest):
    t0 = time.time()
    logger.info(f"[Gemini] POST /gemini model={request.model} msg=\"{_truncate(request.message)}\"")

    try:
        gemini_client = get_gemini_client()
    except GeminiClientNotInitializedError as e:
        logger.warning(f"[Gemini] Client not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e))

    try:
        files: Optional[List[Union[str, Path]]] = [Path(f) for f in request.files] if request.files else None
        response = await gemini_client.generate_content(request.message, request.model, files=files, gem=request.gem)
        elapsed = time.time() - t0
        logger.info(f"[Gemini] OK model={request.model} {len(response.text)} chars in {elapsed:.1f}s")
        return {"response": response.text}
    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[Gemini] ERROR after {elapsed:.1f}s: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating content: {str(e)}")


@router.post("/gemini-chat")
async def gemini_chat(request: GeminiRequest):
    t0 = time.time()
    logger.info(f"[Gemini] POST /gemini-chat model={request.model} msg=\"{_truncate(request.message)}\"")

    try:
        gemini_client = get_gemini_client()
    except GeminiClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    session_manager = get_gemini_chat_manager()
    if not session_manager:
        raise HTTPException(status_code=503, detail="Session manager is not initialized.")
    try:
        response = await session_manager.get_response(request.model, request.message, request.files, request.gem)
        elapsed = time.time() - t0
        logger.info(f"[Gemini] Chat OK model={request.model} {len(response.text)} chars in {elapsed:.1f}s")
        return {"response": response.text}
    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[Gemini] Chat ERROR after {elapsed:.1f}s: {e}")
        raise HTTPException(status_code=500, detail=f"Error in chat: {str(e)}")
