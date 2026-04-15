import pytest
from pydantic import BaseModel
from app.llm import LLM, LLMParseError

class Shape(BaseModel):
    answer: str
    score: int

@pytest.mark.asyncio
async def test_structured_retry_on_bad_json(monkeypatch):
    llm = LLM()
    call_count = {"n": 0}

    async def fake_chat(messages, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "not json"
        return '{"answer": "ok", "score": 3}'

    monkeypatch.setattr(llm, "_chat_raw", fake_chat)
    result = await llm.structured(messages=[{"role": "user", "content": "x"}], schema=Shape)
    assert result.answer == "ok" and result.score == 3
    assert call_count["n"] == 2

@pytest.mark.asyncio
async def test_structured_fails_after_second_bad_json(monkeypatch):
    llm = LLM()
    async def fake_chat(messages, **kw): return "still not json"
    monkeypatch.setattr(llm, "_chat_raw", fake_chat)
    with pytest.raises(LLMParseError):
        await llm.structured(messages=[{"role": "user", "content": "x"}], schema=Shape)
