"""Optional Claude layer (opt-in, OFF by default).

Enabled only when BOTH `NOWKB_LLM=1` and an Anthropic credential are set. It is used for one thing:
rewriting a low-confidence *generic* (free-text) answer from vetted, current evidence. It never
touches rate-table answers, and every model answer must pass `validate()` — numbers must be grounded
in the cited evidence (or the question), no known-stale value may appear, and the evidence ids must be
real — otherwise the deterministic answer stands. Calls are hard-timed-out and never retried, so a
slow or failing API costs at most a few seconds and never an answer.

It could not be measured during development (no API key), which is why it is off by default.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

MODEL = os.getenv("NOWKB_LLM_MODEL", "claude-haiku-5-5")
TIMEOUT_S = float(os.getenv("NOWKB_LLM_TIMEOUT", "4"))

SYSTEM = """You answer credit-union members' questions using ONLY the numbered evidence snippets provided.
Rules:
- Use only facts stated in the evidence. Copy numbers, dates, times, phone numbers and URLs exactly as written.
- Prefer the newest and most official snippet when snippets disagree; never mention superseded values.
- Answer directly in 1-3 sentences. Do not ask the member for a ZIP code or member number.
- If the evidence does not contain the answer, set status to "not_listed".
Return JSON: {"status": "answer" | "not_listed", "evidence_ids": [ids you used], "answer": "..."}"""

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class Evidence:
    eid: str
    url: str
    text: str


def enabled() -> bool:
    return os.getenv("NOWKB_LLM") == "1" and bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _nums(s: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(s or "")}


def validate(answer: str, used: list[Evidence], question: str, stale: set[str]) -> Optional[str]:
    """Return a reason string if the answer must be rejected, else None."""
    if not answer or len(answer) > 900:
        return "empty or too long"
    if not used:
        return "no evidence cited"
    grounded = _nums(" ".join(e.text for e in used)) | _nums(question)
    loose = _nums(answer) - grounded
    if loose:
        return f"ungrounded numbers {sorted(loose)}"
    for v in stale:
        if v and v in answer:
            return f"stale value {v}"
    if re.search(r"(?i)zip code|member number|in these facts|based on the (?:provided )?context", answer):
        return "forbidden phrasing"
    return None


class Composer:
    def __init__(self, client=None) -> None:
        self._client = client
        self.calls = 0
        self.rejections: list[str] = []

    def _get_client(self):
        if self._client is None:
            import anthropic  # optional dependency
            self._client = anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=0)
        return self._client

    def compose(self, question: str, evidence: list[Evidence], stale: set[str] = frozenset()) -> Optional[dict]:
        """-> {"status": "answer"|"not_listed", "answer": str, "evidence": [Evidence]} or None (use fallback)."""
        if not evidence:
            return None
        body = "\n\n".join(f"[{e.eid}] ({e.url})\n{e.text[:900]}" for e in evidence)
        try:
            self.calls += 1
            resp = self._get_client().messages.create(
                model=MODEL,
                max_tokens=400,
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": f"Evidence:\n{body}\n\nQuestion: {question}"}],
            )
            if getattr(resp, "stop_reason", None) == "refusal":
                return None
            text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
            m = re.search(r"\{.*\}", text, re.S)
            data = json.loads(m.group(0)) if m else {}
        except Exception as e:  # network, auth, parse, timeout: the deterministic answer stands
            self.rejections.append(f"error: {type(e).__name__}")
            return None
        status = data.get("status")
        by_id = {e.eid: e for e in evidence}
        used = [by_id[i] for i in data.get("evidence_ids", []) if i in by_id]
        if status == "not_listed":
            return {"status": "not_listed", "answer": "", "evidence": []}
        answer = str(data.get("answer", "")).strip()
        why = validate(answer, used, question, stale)
        if why:
            self.rejections.append(why)
            return None
        return {"status": "answer", "answer": answer, "evidence": used}
