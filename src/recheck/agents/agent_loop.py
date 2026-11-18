"""Would an LLM agent re-check on its own? A probe run alongside the certified memory.

On a sample of queries the probe shows an LLM agent the task and what memory holds (value, age,
source), with or without the certificate's verdict, and asks it to answer from memory or call
the tool first. The probe does not change the memory or the certified policy, so both are judged
on exactly the same belief states: how often the agent serves stale values on its own, how
often it re-checks needlessly, and whether a certificate in its context changes its behaviour.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..types import Belief
from ..world.render import describe_belief, describe_task
from .llm import DEFAULT_BASE, DEFAULT_MODEL, ChatClient

AGENT_PROMPT = """You are an agent completing a task. Calling the tool costs time and money;
answering from memory is free but the world changes and memory is not told.

Task: {task}

What your memory holds:
{belief}
{cert}
Reply with JSON only: {{"action": "answer"}} to answer from memory, or {{"action": "check"}} to call
the tool and get the current value first."""

CERT_YES = ("Memory certificate: answers like this one are certified (the risk of a stale answer "
            "from this class of memory is below {alpha:.0%}).\n")
CERT_NO = "Memory certificate: this answer is NOT certified; re-checking is recommended.\n"


@dataclass
class LLMAgentProbe:
    base_url: str = DEFAULT_BASE
    model: str = DEFAULT_MODEL
    show_certificate: bool = False
    alpha: float = 0.05
    max_calls: int = 1000
    _client: ChatClient | None = None

    @property
    def name(self) -> str:
        return f"llm-agent{'+cert' if self.show_certificate else ''}"

    def __call__(self, b: Belief, slot: str, t: float, certified: bool) -> str | None:
        if self._client is None:
            self._client = ChatClient(self.base_url, self.model)
        if self._client.calls >= self.max_calls:
            return None
        cert = ""
        if self.show_certificate:
            cert = CERT_YES.format(alpha=self.alpha) if certified else CERT_NO
        text = self._client.chat([{"role": "user", "content": AGENT_PROMPT.format(
            task=describe_task(slot), belief=describe_belief(b, t), cert=cert)}], max_tokens=30)
        try:
            act = json.loads(text).get("action", "")
        except Exception:
            act = "check" if "check" in (text or "").lower() else "answer"
        return "check" if str(act).lower().startswith("check") else "answer"
