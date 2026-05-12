"""
Pure curl_cffi-based ChatGPT client.
Bypasses Cloudflare via TLS impersonation and solves the sentinel PoW challenge.
"""
import json
import uuid
import time
import sqlite3
import tempfile
import shutil
import os
from typing import Generator
from curl_cffi import requests
from .pow import solve_challenge


class ChatGPTClient:
    """ChatGPT web API client using curl_cffi + PoW solving."""

    BASE = "https://chatgpt.com/backend-anon"

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
        """Get sentinel token and solve PoW challenge (with caching)."""
        now = time.time()
        if self._sentinel_cache and (now - self._sentinel_cache[2]) < self._cache_ttl:
            return self._sentinel_cache[0], self._sentinel_cache[1]

        resp = requests.post(
            f"{self.BASE}/sentinel/chat-requirements",
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

    def ask(self, prompt: str, model: str = "") -> Generator[str, None, None]:
        """Send a message and yield text chunks (deltas)."""
        st, proof = self._get_sentinel_token()
        msg_id = str(uuid.uuid4())
        parent_id = str(uuid.uuid4())

        resp = requests.post(
            f"{self.BASE}/conversation",
            headers={
                **self._base_headers,
                "accept": "text/event-stream",
                "openai-sentinel-chat-requirements-token": st,
                "openai-sentinel-proof-token": proof,
            },
            cookies=self._cookies,
            json={
                "action": "next",
                "messages": [
                    {
                        "id": msg_id,
                        "author": {"role": "user"},
                        "role": "user",
                        "content": {"content_type": "text", "parts": [prompt]},
                    }
                ],
                "conversation_id": None,
                "parent_message_id": parent_id,
                "model": model or "",
                "history_and_training_disabled": True,
            },
            impersonate="chrome120",
            stream=True,
            timeout=60,
        )

        if resp.status_code != 200:
            raise Exception(f"ChatGPT API error: {resp.status_code} {resp.text[:200]}")

        prev_text = ""
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
                        full_text = parts[0]
                        delta = full_text[len(prev_text):]
                        if delta:
                            yield delta
                        prev_text = full_text
                except json.JSONDecodeError:
                    pass

    def ask_blocking(self, prompt: str, model: str = "") -> str:
        """Send a message and return the full response."""
        st, proof = self._get_sentinel_token()
        msg_id = str(uuid.uuid4())
        parent_id = str(uuid.uuid4())

        resp = requests.post(
            f"{self.BASE}/conversation",
            headers={
                **self._base_headers,
                "accept": "text/event-stream",
                "openai-sentinel-chat-requirements-token": st,
                "openai-sentinel-proof-token": proof,
            },
            cookies=self._cookies,
            json={
                "action": "next",
                "messages": [
                    {
                        "id": msg_id,
                        "author": {"role": "user"},
                        "role": "user",
                        "content": {"content_type": "text", "parts": [prompt]},
                    }
                ],
                "conversation_id": None,
                "parent_message_id": parent_id,
                "model": model or "",
                "history_and_training_disabled": True,
            },
            impersonate="chrome120",
            stream=True,
            timeout=60,
        )

        if resp.status_code != 200:
            raise Exception(f"ChatGPT API error: {resp.status_code} {resp.text[:200]}")

        final = ""
        for line in resp.iter_lines():
            if not line:
                continue
            t = line.decode()
            if "data: [DONE]" in t:
                break
            if t.startswith("data: "):
                try:
                    d = json.loads(t[6:])
                    status = d.get("message", {}).get("status", "")
                    parts = d.get("message", {}).get("content", {}).get("parts", [])
                    if status == "finished_successfully" and parts and parts[0]:
                        final = parts[0]
                except json.JSONDecodeError:
                    pass

        return final
