from pydantic import BaseModel
from typing import Literal

class Bbox(BaseModel):
    page: int
    bbox: tuple[float, float, float, float]  # full page rect

class Page(BaseModel):
    page_no: int
    markdown: str            # vision-extracted markdown for the page
    width: float
    height: float
    failed: bool = False     # vision call failed for this page

class Section(BaseModel):
    id: str
    title: str
    level: int
    page_start: int
    page_end: int
    text: str                # concatenated page markdown belonging to this section

class Chunk(BaseModel):
    id: str
    section_id: str | None
    page: int
    text: str
    token_count: int
    bboxes: list[Bbox]       # page-level bbox only

class DocMeta(BaseModel):
    company: str | None = None
    filing_type: str | None = None
    period_end: str | None = None

class StructuredDoc(BaseModel):
    doc_id: str
    n_pages: int
    meta: DocMeta = DocMeta()
    pages: list[Page]
    sections: list[Section]
    chunks: list[Chunk]
