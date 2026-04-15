from __future__ import annotations
import asyncio
from functools import lru_cache
from openai import AsyncAzureOpenAI
from sentence_transformers import SentenceTransformer
from ..settings import settings
from ..logging import log

@lru_cache(maxsize=1)
def _local_model() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_fallback_model)

class EmbeddingService:
    def __init__(self, force_local: bool = False):
        self.mode: str = "local" if force_local else "unset"
        self.client: AsyncAzureOpenAI | None = None if force_local else AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )

    async def _probe_azure(self) -> None:
        assert self.client is not None
        try:
            await self.client.embeddings.create(
                model=settings.azure_openai_embedding_deployment, input=["probe"])
            self.mode = "azure"
            log.info("embeddings.azure.ok")
        except Exception as e:
            log.warning("embeddings.azure.unavailable", error=str(e)[:200])
            self.mode = "local"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.mode == "unset": await self._probe_azure()
        if self.mode == "azure":
            assert self.client is not None
            resp = await self.client.embeddings.create(
                model=settings.azure_openai_embedding_deployment, input=texts)
            return [d.embedding for d in resp.data]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _local_model().encode(texts, normalize_embeddings=True).tolist())
