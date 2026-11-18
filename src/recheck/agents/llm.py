"""An OpenAI-compatible chat client (Ollama, vLLM, LM Studio, OpenAI) with a disk cache, and an
LLM judge that estimates whether a remembered value has gone stale.

Ollama serves the OpenAI API at http://localhost:11434/v1, so the same client runs on a laptop,
in Colab or on Kaggle (see notebooks/). No dependency beyond the standard library.

Set RECHECK_OFFLINE=1 to fail on any request that is not cached (exact replays).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..types import Belief
from ..world.render import describe_belief
from .judges import Judge

DEFAULT_BASE = os.environ.get("RECHECK_LLM_BASE", "http://localhost:11434/v1")
DEFAULT_MODEL = os.environ.get("RECHECK_LLM_MODEL", "qwen2.5:3b")


@dataclass
class ChatClient:
    base_url: str = DEFAULT_BASE
    model: str = DEFAULT_MODEL
    api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", "ollama"))
    cache_path: str = "cache/llm_cache.sqlite"
    temperature: float = 0.0
    timeout: float = 120.0
    calls: int = 0
    cached: int = 0

    def __post_init__(self) -> None:
        Path(self.cache_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.cache_path)
        self._db.execute("create table if not exists c (k text primary key, v text)")

    def chat(self, messages: list[dict], max_tokens: int = 200, json_mode: bool = True) -> str:
        body = {"model": self.model, "messages": messages, "temperature": self.temperature,
                "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        key = hashlib.sha256(json.dumps([self.base_url, body], sort_keys=True).encode()).hexdigest()
        row = self._db.execute("select v from c where k = ?", (key,)).fetchone()
        if row:
            self.cached += 1
            return row[0]
        if os.environ.get("RECHECK_OFFLINE") == "1":
            raise RuntimeError("RECHECK_OFFLINE=1 and this request is not cached")
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out = json.loads(r.read())["choices"][0]["message"]["content"]
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        self.calls += 1
        self._db.execute("insert or replace into c values (?, ?)", (key, out))
        self._db.commit()
        return out


JUDGE_PROMPT = """You keep an AI agent's memory. The world keeps changing and nobody tells the
memory.
Estimate the probability that the stored value below is no longer correct right now.

{belief}

Reply with JSON only: {{"p_changed": <a number from 0 to 100>}}"""


def parse_probability(text: str) -> float | None:
    try:
        obj = json.loads(text)
        for k in ("p_changed", "probability", "p", "prob"):
            if k in obj:
                return min(1.0, max(0.0, float(obj[k]) / 100.0))
    except Exception:
        pass
    m = re.search(r"(\d+(?:\.\d+)?)", text or "")
    if m:
        v = float(m.group(1))
        return min(1.0, max(0.0, v / 100.0 if v > 1 else v))
    return None


@dataclass
class LLMJudge(Judge):
    """Asks a chat model how likely a belief is stale. `max_calls` caps the budget; beyond it the
    judge returns None, which the certifier treats as J = 0 (still valid, just less efficient)."""

    base_url: str = DEFAULT_BASE
    model: str = DEFAULT_MODEL
    max_calls: int = 2000
    every: int = 1               # judge every k-th belief (subsampling keeps validity)
    name: str = "llm"
    _client: ChatClient | None = None
    _n: int = 0

    def __call__(self, b: Belief, t, world, stale, rng, context=None):
        self._n += 1
        if self._n % self.every:
            return None
        if self._client is None:
            self._client = ChatClient(self.base_url, self.model)
        if self._client.calls >= self.max_calls:
            return None
        text = self._client.chat([{"role": "user",
                                   "content": JUDGE_PROMPT.format(belief=describe_belief(b, t))}],
                                 max_tokens=40)
        return parse_probability(text)
