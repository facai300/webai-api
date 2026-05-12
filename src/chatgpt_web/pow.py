"""
ChatGPT Proof-of-Work solver.
Based on reverse-engineering of chatgpt.com's sentinel challenge.
"""
import hashlib
import base64
import json
import time
import math
import random


def solve_challenge(seed: str, difficulty: str, max_iterations: int = 200000) -> str | None:
    """
    Solve a PoW challenge from ChatGPT's sentinel endpoint.

    Args:
        seed: The challenge seed string
        difficulty: Hex difficulty string (e.g. "0000ffff...")
        max_iterations: Max nonce attempts

    Returns:
        Proof token string (gAAAAAB...) or None if not solved.
    """
    cores = random.choice([8, 12, 16, 24])
    screen = random.choice([3000, 4000, 6000])
    diff_len = len(difficulty)
    diff_int = int(difficulty[:16], 16) if len(difficulty) >= 16 else int(difficulty, 16) << (64 - len(difficulty) * 4)

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
    ts = int(time.time() * 1000)

    for nonce in range(max_iterations):
        config = [cores + screen, ts, 4294705152, nonce, ua]
        payload = base64.b64encode(json.dumps(config).encode()).decode()
        data = seed + payload
        h = hashlib.sha3_512(data.encode()).hexdigest()

        if h[:diff_len] <= difficulty:
            return "gAAAAAB" + payload

    return None


def generate_fake_token() -> str:
    """Generate a fake sentinel token for initial chat-requirements request."""
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
    config = [
        random.randint(3000, 6000),
        time.strftime("%a %b %d %Y %H:%M:%S GMT+0100 (Central European Time)"),
        4294705152,
        0,
        ua,
        "de", "de",
        401,
        "mediaSession",
        "location",
        round(random.random() * 4000 + 1000, 2),
        "",
        "",
        12,
        int(time.time() * 1000),
    ]
    payload = base64.b64encode(json.dumps(config).encode()).decode()
    return "gAAAAAC" + payload
