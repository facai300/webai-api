# src/app/endpoints/chat.py
import json
import time
from typing import Optional
from fastapi import APIRouter, HTTPException
from app.logger import logger
from schemas.request import GeminiRequest, OpenAIChatRequest
from app.services.gemini_client import get_gemini_client, GeminiClientNotInitializedError
from app.services.deepseek_client import get_deepseek_client, DeepSeekClientNotInitializedError
from app.services.session_manager import get_translate_session_manager

router = APIRouter()

@router.get("/v1/gems")
async def list_gems():
    try:
        gemini_client = get_gemini_client()
    except GeminiClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        gems = await gemini_client.fetch_gems()
        return {
            "gems": [
                {
                    "id": gem.id,
                    "name": gem.name,
                    "description": gem.description,
                    "predefined": gem.predefined,
                }
                for gem in gems
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching gems: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching gems: {str(e)}")


@router.post("/translate")
async def translate_chat(request: GeminiRequest):
    try:
        gemini_client = get_gemini_client()
    except GeminiClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    session_manager = get_translate_session_manager()
    if not session_manager:
        raise HTTPException(status_code=503, detail="Session manager is not initialized.")
    try:
        response = await session_manager.get_response(request.model, request.message, request.files, request.gem)
        return {"response": response.text}
    except Exception as e:
        logger.error(f"Error in /translate endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error during translation: {str(e)}")


def _build_tools_prompt(tools: list) -> str:
    """Convert OpenAI tool definitions to a system prompt for Gemini."""
    declarations = []
    for t in tools:
        if t.get("type") == "function" and "function" in t:
            declarations.append(t["function"])
    if not declarations:
        return ""
    lines = [
        "You have access to the following tools. When you want to call a tool, respond with "
        "ONLY a JSON object in this exact format, with no other text before or after:\n"
        '{"tool_call": {"name": "<tool_name>", "arguments": {<arguments>}}}\n',
        "Available tools:",
    ]
    for fn in declarations:
        lines.append(f"- {fn['name']}: {fn.get('description', '')}")
        if fn.get("parameters"):
            lines.append(f"  Parameters: {json.dumps(fn['parameters'])}")
    return "\n".join(lines)


def _parse_tool_call(text: str) -> Optional[dict]:
    """Extract a tool_call JSON object from model response text."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == '{':
            try:
                obj, _ = decoder.raw_decode(text, i)
                if isinstance(obj, dict) and "tool_call" in obj:
                    return obj["tool_call"]
            except (json.JSONDecodeError, ValueError):
                pass
    return None


def convert_to_openai_format(response_text: str, model: str, stream: bool = False, tool_call: Optional[dict] = None):
    ts = int(time.time())
    choice_key = "delta" if stream else "message"
    
    if tool_call:
        args = tool_call.get("arguments", {})
        content = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{ts}",
                "type": "function",
                "function": {
                    "name": tool_call.get("name", ""),
                    "arguments": json.dumps(args) if isinstance(args, dict) else args,
                },
            }],
        }
        return {
            "id": f"chatcmpl-{ts}",
            "object": "chat.completion.chunk" if stream else "chat.completion",
            "created": ts,
            "model": model,
            "choices": [{
                "index": 0,
                choice_key: content,
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return {
        "id": f"chatcmpl-{ts}",
        "object": "chat.completion.chunk" if stream else "chat.completion",
        "created": ts,
        "model": model,
        "choices": [{
            "index": 0,
            choice_key: {
                "role": "assistant",
                "content": response_text,
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _messages_to_prompt(messages: list, tools: Optional[list] = None) -> str:
    """Convert OpenAI-style messages to a flat prompt string."""
    parts = []

    # Extract tools prompt
    tools_prompt = _build_tools_prompt(tools) if tools else ""
    tools_appended = False

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content") or ""

        if role == "system":
            combined = f"System: {content}"
            if tools_prompt and not tools_appended:
                combined = f"{combined}\n\n{tools_prompt}"
                tools_appended = True
            parts.append(combined)
        elif role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    parts.append(
                        f"Assistant called tool {fn.get('name')}: {fn.get('arguments', '')}"
                    )
            elif content:
                parts.append(f"Assistant: {content}")
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            parts.append(f"Tool result [{tool_call_id}]: {content}")

    # If no system message, prepend tools prompt at the beginning
    if tools_prompt and not tools_appended:
        parts.insert(0, tools_prompt)

    return "\n\n".join(parts)


@router.get("/v1/models")
async def list_models():
    ts = int(time.time())
    models = []
    # Gemini models
    try:
        from gemini_webapi.constants import Model
        for m in Model:
            if m != Model.UNSPECIFIED:
                models.append({
                    "id": m.model_name,
                    "object": "model",
                    "created": ts,
                    "owned_by": "google",
                })
    except ImportError:
        pass
    # DeepSeek models
    for m in ["deepseek-v3", "deepseek-r1"]:
        models.append({
            "id": m,
            "object": "model",
            "created": ts,
            "owned_by": "deepseek",
        })
    # ChatGPT models (web version)
    for m in ["gpt-4o", "gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]:
        models.append({
            "id": m,
            "object": "model",
            "created": ts,
            "owned_by": "chatgpt-web",
        })
    return {"object": "list", "data": models}


@router.post("/v1/chat/completions")
async def chat_completions(request: OpenAIChatRequest):
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided.")
    if not request.model:
        raise HTTPException(status_code=400, detail="Model not specified in the request.")

    is_stream = request.stream if request.stream is not None else False
    is_deepseek = request.model.startswith("deepseek-")
    is_chatgpt = request.model.startswith("gpt-")

    # Convert messages to prompt (shared logic)
    final_prompt = _messages_to_prompt(request.messages, request.tools)

    try:
        if is_deepseek:
            return await _route_to_deepseek(final_prompt, request, is_stream)
        elif is_chatgpt:
            return await _route_to_chatgpt(final_prompt, request, is_stream)
        else:
            return await _route_to_gemini(final_prompt, request, is_stream)
    except Exception as e:
        logger.error(f"Error in /v1/chat/completions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


async def _route_to_gemini(prompt: str, request: OpenAIChatRequest, is_stream: bool):
    """Handle /v1/chat/completions via Gemini."""
    try:
        gemini_client = get_gemini_client()
    except GeminiClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    response = await gemini_client.generate_content(
        message=prompt, model=request.model, files=None, gem=request.gem
    )
    response_text = response.text if hasattr(response, "text") else str(response)
    logger.debug(f"Gemini raw response: {response_text!r}")
    tool_call = _parse_tool_call(response_text) if request.tools else None

    openai_response = convert_to_openai_format(response_text, request.model, is_stream, tool_call)

    if is_stream:
        from fastapi.responses import StreamingResponse
        async def sse_stream():
            yield f"data: {json.dumps(openai_response)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    return openai_response


async def _route_to_deepseek(prompt: str, request: OpenAIChatRequest, is_stream: bool):
    """Handle /v1/chat/completions via DeepSeek."""
    try:
        ds_client = get_deepseek_client()
    except DeepSeekClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if is_stream:
        from fastapi.responses import StreamingResponse

        async def sse_stream():
            ts = int(time.time())
            chunk_id = f"chatcmpl-{ts}"
            try:
                async for chunk in ds_client.generate_stream(
                    prompt, model=request.model,
                ):
                    if chunk.get("type") != "text":
                        continue
                    if chunk.get("finish_reason") == "stop":
                        # Final chunk with stop reason
                        sse_data = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": ts,
                            "model": request.model,
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop",
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
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    # Non-streaming
    response_text = await ds_client.generate_content(prompt, model=request.model)
    openai_response = convert_to_openai_format(response_text, request.model, stream=False)
    return openai_response


async def _route_to_chatgpt(prompt: str, request: OpenAIChatRequest, is_stream: bool):
    """Handle /v1/chat/completions via ChatGPT web."""
    from app.services.chatgpt_client import get_chatgpt_client, ChatGPTClientNotInitializedError
    try:
        gpt_client = get_chatgpt_client()
    except ChatGPTClientNotInitializedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Reset conversation so each request is independent
    await gpt_client.reset_conversation()

    if is_stream:
        from fastapi.responses import StreamingResponse

        async def sse_stream():
            import time
            ts = int(time.time())
            chunk_id = f"chatcmpl-{ts}"
            try:
                async for chunk in gpt_client.generate_stream(
                    prompt, model="auto",
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
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    # Non-streaming
    response_text = await gpt_client.generate_content(prompt, model="auto")
    openai_response = convert_to_openai_format(response_text, request.model, stream=False)
    # Reset conversation for next request
    await gpt_client.reset_conversation()
    return openai_response
