from ..llm import llm
from .schema import StructuredDoc, DocMeta

async def extract_doc_meta(doc: StructuredDoc) -> DocMeta:
    head = "\n\n".join(p.markdown for p in doc.pages[:3])[:6000]
    prompt = (
        "Extract the issuer name, filing type (e.g. 10-K, 10-Q, earnings call), "
        "and period_end date (YYYY-MM-DD if available) from the following filing header. "
        "Return JSON fields: company, filing_type, period_end. Unknown fields → null.\n\n"
        f"{head}"
    )
    return await llm.structured(messages=[{"role": "user", "content": prompt}], schema=DocMeta)
