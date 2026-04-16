from ..llm import llm
from .types import DecompositionPlan


async def decompose(
    *, prompt: str, doc_meta: dict, section_index: list[dict], shape_hint: str,
) -> DecompositionPlan:
    sections_md = "\n".join(f"- [{s['id']}] {s['title']}" for s in section_index[:40])
    msg = (
        "You are preparing an information-extraction plan for one cell of a matrix.\n"
        f"Document: {doc_meta}\n"
        f"Available sections:\n{sections_md}\n\n"
        f"User prompt: {prompt}\n"
        f"Requested answer shape hint: {shape_hint}\n\n"
        "Return JSON with:\n"
        "- sub_questions: 2-4 specific retrieval queries that together cover the prompt\n"
        "- expected_answer_shape: one of text|number|currency|percentage|list|table\n"
        "- target_sections: up to 3 section ids most likely to contain the answer\n"
    )
    return await llm.structured(
        messages=[{"role": "user", "content": msg}],
        schema=DecompositionPlan,
        max_tokens=600,
    )
