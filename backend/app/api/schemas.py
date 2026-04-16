from pydantic import BaseModel


class CreateWorkspaceIn(BaseModel):
    name: str


class CreateGridIn(BaseModel):
    workspace_id: str
    name: str
    retriever_mode: str = "wiki"


class AddColumnIn(BaseModel):
    prompt: str
    shape_hint: str = "text"


class EditColumnIn(BaseModel):
    prompt: str | None = None
    shape_hint: str | None = None


class SetRetrieverIn(BaseModel):
    retriever_mode: str


class SynthesizeIn(BaseModel):
    prompt: str
    row_ids: list[str] | None = None
    column_ids: list[str] | None = None


class SuggestIn(BaseModel):
    prompt: str
