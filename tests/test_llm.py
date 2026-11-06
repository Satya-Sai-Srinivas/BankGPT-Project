"""The optional Claude layer, exercised with a stub client (no network, no key)."""
import json
from types import SimpleNamespace

from nowkb.llm import Composer, Evidence, validate

EV = [Evidence("E1", "https://x/join", "To join Dupaco, simply open a savings account with $25 or more.")]


class Stub:
    def __init__(self, payload, raise_exc=None):
        self.payload, self.raise_exc = payload, raise_exc
        self.messages = self

    def create(self, **kw):
        assert "temperature" not in kw            # sampling params are rejected by current models
        if self.raise_exc:
            raise self.raise_exc
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def test_grounded_answer_is_accepted():
    c = Composer(client=Stub({"status": "answer", "evidence_ids": ["E1"], "answer": "Open a savings account with $25."}))
    r = c.compose("How much to join?", EV)
    assert r and r["status"] == "answer" and "$25" in r["answer"]


def test_ungrounded_number_is_rejected():
    c = Composer(client=Stub({"status": "answer", "evidence_ids": ["E1"], "answer": "It costs $50."}))
    assert c.compose("How much to join?", EV) is None
    assert "ungrounded" in c.rejections[0]


def test_stale_value_and_errors_fall_back():
    assert validate("Rate is 5.34%", EV, "q", {"5.34%"}) is not None
    c = Composer(client=Stub({}, raise_exc=TimeoutError("slow")))
    assert c.compose("q", EV) is None


def test_off_by_default(monkeypatch):
    from nowkb import llm
    monkeypatch.delenv("NOWKB_LLM", raising=False)
    assert llm.enabled() is False
