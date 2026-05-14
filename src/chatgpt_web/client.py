"""
ChatGPT web API client with file upload support.
Uses curl_cffi for Cloudflare bypass + PoW solving, httpx for Azure blob upload.
"""
import json
import uuid
import time
import sqlite3
import tempfile
import shutil
import os
import mimetypes
import logging
from pathlib import Path
from typing import Generator, Optional
from curl_cffi import requests
import httpx
from .pow import solve_challenge

logger = logging.getLogger("chatgpt_web")


class ChatGPTClient:
    """ChatGPT web API client using curl_cffi + PoW solving.
    Uses authenticated endpoint when access_token is provided."""

    BASE = "https://chatgpt.com/backend-api"  # auth endpoint
    BASE_ANON = "https://chatgpt.com/backend-anon"  # fallback
    MAX_PROMPT_LEN = 20000  # prompt chars hard limit (f/conversation returns 413 beyond ~25K)

    def __init__(self, access_token: str = ""):
        self.access_token = access_token
        self._base_headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": "https://chatgpt.com",
            "referer": "https://chatgpt.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        }
        if access_token:
            self._base_headers["authorization"] = f"Bearer {access_token}"
        self._cookies = self._load_firefox_cookies()
        self._sentinel_cache = None  # (st, proof, timestamp)
        self._cache_ttl = 120  # seconds

    @staticmethod
    def _load_firefox_cookies() -> dict:
        """Load chatgpt.com cookies from Firefox (including Snap)."""
        home = os.path.expanduser("~")
        import glob as g
        paths = g.glob(os.path.join(home, ".mozilla", "firefox", "*.default*", "cookies.sqlite"))
        if not paths:
            paths = g.glob(os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox", "*.default*", "cookies.sqlite"))
        if not paths:
            return {}
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                tmp = tf.name
                shutil.copy2(paths[0], tmp)
            conn = sqlite3.connect(tmp)
            cur = conn.cursor()
            cur.execute("SELECT name, value FROM moz_cookies WHERE host LIKE '%chatgpt.com%'")
            ck = {row[0]: row[1] for row in cur.fetchall()}
            conn.close()
            return ck
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def _get_sentinel_token(self) -> tuple[str, str]:
        """Get sentinel token and solve PoW challenge (with caching + fallback)."""
        now = time.time()
        if self._sentinel_cache and (now - self._sentinel_cache[2]) < self._cache_ttl:
            return self._sentinel_cache[0], self._sentinel_cache[1]

        # Try auth endpoint first, fall back to anon
        for base in (self.BASE, self.BASE_ANON):
            try:
                resp = requests.post(
                    f"{base}/sentinel/chat-requirements",
                    headers=self._base_headers,
                    cookies=self._cookies,
                    json={"conversation_kind": "primary"},
                    impersonate="chrome120",
                    timeout=15,
                )
                data = resp.json()
                st = data["token"]
                pw = data.get("proofofwork", {})
                if pw:
                    proof = solve_challenge(pw["seed"], pw["difficulty"])
                    proof = proof or st
                else:
                    proof = st
                self._sentinel_cache = (st, proof, now)
                return st, proof
            except Exception:
                continue

        raise Exception("Failed to get sentinel token from both endpoints")

    def _upload_file(self, file_path: str) -> str:
        """Upload a file and return file_id."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        mime, _ = mimetypes.guess_type(file_path)
        content_type = mime or "application/octet-stream"

        # Step 1: Get upload URL (curl_cffi for Cloudflare bypass)
        resp = requests.post(
            f"{self.BASE}/files",
            headers=self._base_headers,
            cookies=self._cookies,
            json={
                "use_case": "multimodal",
                "file_name": file_name,
                "file_size": file_size,
                "content_type": content_type,
            },
            impersonate="chrome120",
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            raise Exception(f"File upload init failed: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        upload_url = data["upload_url"]
        file_id = data["file_id"]

        # Step 2: PUT file to Azure Blob Storage (httpx, no impersonation needed)
        with open(file_path, "rb") as f:
            file_data = f.read()
        r_put = httpx.put(
            upload_url,
            content=file_data,
            headers={"x-ms-blob-type": "BlockBlob", "Content-Type": content_type},
            timeout=120,
        )
        if r_put.status_code not in (200, 201):
            raise Exception(f"File upload PUT failed: {r_put.status_code}")

        return file_id

    def _build_message(self, prompt: str, file_ids: Optional[list[dict]] = None) -> dict:
        """Build a message dict, with optional file attachments in metadata."""
        # Truncate prompt to avoid 413 Payload Too Large
        if len(prompt) > self.MAX_PROMPT_LEN:
            head = self.MAX_PROMPT_LEN // 4
            tail = self.MAX_PROMPT_LEN - head - 50
            logger.warning(f"Truncating prompt {len(prompt)} -> {self.MAX_PROMPT_LEN} chars")
            prompt = prompt[:head] + (
                f"\n\n...[{len(prompt) - head - tail} chars truncated]...\n\n"
            ) + prompt[-tail:]
        msg = {
            "id": str(uuid.uuid4()),
            "author": {"role": "user"},
            "content": {"content_type": "text", "parts": [prompt]},
            "metadata": {"attachments": [], "developer_mode_connector_ids": []},
        }
        if file_ids:
            for f in file_ids:
                msg["metadata"]["attachments"].append({
                    "id": f["file_id"],
                    "name": f.get("name", "file"),
                    "size": f.get("size", 0),
                    "mime_type": f.get("mime_type", "application/octet-stream"),
                    "source": "library",
                })
        return msg

    def _f_conversation(self, prompt: str, model: str, st: str, proof: str,
                        file_ids: Optional[list[dict]] = None):
        """Send message via f/conversation (supports file attachments)."""
        body = {
            "action": "next",
            "messages": [self._build_message(prompt, file_ids)],
            "parent_message_id": "client-created-root",
            "model": model or "",
            "conversation_mode": {"kind": "primary_assistant"},
            "timezone_offset_min": -480,
        }
        h = {**self._base_headers, "accept": "text/event-stream",
             "openai-sentinel-chat-requirements-token": st,
             "openai-sentinel-proof-token": proof}

        resp = requests.post(
            f"{self.BASE}/f/conversation", headers=h, cookies=self._cookies,
            json=body, impersonate="chrome120", stream=True, timeout=60,
        )
        if resp.status_code == 200:
            return resp
        raise Exception(f"f/conversation error: {resp.status_code}")

    def ask(self, prompt: str, model: str = "", files: Optional[list[str]] = None,
            max_retries: int = 2) -> Generator[str, None, None]:
        """Send a message and yield text deltas. Optionally upload files first.
        Retries on empty response with fresh PoW token."""
        for attempt in range(max_retries + 1):
            file_ids = None
            if files and attempt == 0:  # only upload files on first attempt
                file_ids = []
                for f in files:
                    fid = self._upload_file(f)
                    import os as _os
                    file_ids.append({"file_id": fid, "name": _os.path.basename(f), "size": _os.path.getsize(f),
                                     "mime_type": mimetypes.guess_type(f)[0] or "application/octet-stream"})

            st, proof = self._get_sentinel_token()
            resp = self._f_conversation(prompt, model, st, proof, file_ids)

            prev = ""
            yielded = False
            for line in resp.iter_lines():
                if not line:
                    continue
                t = line.decode()
                if "data: [DONE]" in t:
                    break
                if t.startswith("data: "):
                    try:
                        d = json.loads(t[6:])
                        parts = d.get("message", {}).get("content", {}).get("parts", [])
                        if parts and parts[0]:
                            full = parts[0]
                            # Skip echoed prompt (starts with the input or "User:" prefix)
                            if full == prompt or full.startswith("User:"):
                                prev = full
                                continue
                            # Handle concatenated echo+response
                            for sep in ["User: ", prompt]:
                                if full.startswith(sep):
                                    full = full[len(sep):].strip()
                                    break
                            delta = full[len(prev):] if prev and full.startswith(prev) else full
                            prev = full
                            if delta:
                                yielded = True
                                yield delta
                    except json.JSONDecodeError:
                        pass

            # If we got content, done. Otherwise retry with fresh token.
            if yielded:
                return
            if attempt < max_retries:
                logger.warning(
                    f"ChatGPT stream empty (attempt {attempt+1}/{max_retries}), "
                    f"prompt_len={len(prompt)} model={model}"
                )
                # Clear PoW cache to get fresh token
                self._sentinel_cache = None
                files = None  # don't re-upload on retry
            else:
                logger.error(
                    f"ChatGPT stream empty after all {max_retries+1} attempts, "
                    f"prompt_len={len(prompt)} model={model}"
                )

    def ask_blocking(self, prompt: str, model: str = "", files: Optional[list[str]] = None,
                     max_retries: int = 2) -> str:
        """Send a message and return full response. Optionally upload files first.
        Retries on empty response with fresh PoW token."""
        for attempt in range(max_retries + 1):
            file_ids = None
            if files and attempt == 0:  # only upload files on first attempt
                file_ids = []
                for f in files:
                    fid = self._upload_file(f)
                    import os as _os
                    file_ids.append({"file_id": fid, "name": _os.path.basename(f), "size": _os.path.getsize(f),
                                     "mime_type": mimetypes.guess_type(f)[0] or "application/octet-stream"})
            st, proof = self._get_sentinel_token()
            resp = self._f_conversation(prompt, model, st, proof, file_ids)

            last = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                t = line.decode()
                if "data: [DONE]" in t:
                    break
                if t.startswith("data: "):
                    try:
                        d = json.loads(t[6:])
                        parts = d.get("message", {}).get("content", {}).get("parts", [])
                        if parts and parts[0]:
                            last = parts[0]
                    except json.JSONDecodeError:
                        pass
            # Strip echoed prompt
            for p in [f"User: {prompt}", prompt, "User: "]:
                if last.startswith(p):
                    last = last[len(p):].strip()
                    break

            if last.strip():
                return last
            if attempt < max_retries:
                import logging
                logging.getLogger(__name__).warning(
                    f"ChatGPT blocking returned empty response (attempt {attempt+1}), retrying..."
                )
                self._sentinel_cache = None
                files = None
            else:
                import logging
                logging.getLogger(__name__).error(
                    f"ChatGPT blocking returned empty after {max_retries+1} attempts"
                )
        return ""
