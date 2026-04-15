from pydantic import BaseModel
from typing import Protocol
from ..parser.schema import Bbox, StructuredDoc

class Evidence(BaseModel):
    chunk_id: str
    text: str
    page: int
    bboxes: list[Bbox]
    score: float
    source: str  # "chunk.vector" | "wiki.metric" | "wiki.claim" | "section.drill" | "chunk.isd"

class Retriever(Protocol):
    async def retrieve(self, query: str, doc: StructuredDoc, k: int = 8) -> list[Evidence]: ...
