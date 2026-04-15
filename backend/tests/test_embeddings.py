import pytest
from app.retriever.embeddings import EmbeddingService

@pytest.mark.asyncio
async def test_local_fallback():
    svc = EmbeddingService(force_local=True)
    vecs = await svc.embed(["hello world", "another doc"])
    assert len(vecs) == 2 and len(vecs[0]) > 100
