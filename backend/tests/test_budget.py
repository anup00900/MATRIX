import pytest, asyncio
from app.jobs.budget import TokenBudget

@pytest.mark.asyncio
async def test_acquire_blocks_when_empty():
    b = TokenBudget(tokens_per_minute=7200, burst=60)  # 120 tok/sec
    await b.acquire(60)
    t0 = asyncio.get_event_loop().time()
    await b.acquire(60)
    elapsed = asyncio.get_event_loop().time() - t0
    assert 0.4 < elapsed < 0.7
