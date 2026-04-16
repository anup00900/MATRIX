import pytest
from sqlmodel import Session
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import settings as s_mod
    monkeypatch.setattr(s_mod.settings, "storage_root", tmp_path)
    s_mod.settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    for d in (s_mod.settings.pdfs_dir, s_mod.settings.parsed_dir,
              s_mod.settings.wikis_dir, s_mod.settings.vectors_dir,
              s_mod.settings.traces_dir):
        d.mkdir(parents=True, exist_ok=True)

    from app.storage import db as db_mod
    db_mod.init_db(reset=True)

    from app.services import cells as cells_mod
    async def noop_job(*, cell_id: str): return None
    monkeypatch.setattr(cells_mod, "run_cell_job", noop_job)
    from app.api import routes as routes_mod
    monkeypatch.setattr(routes_mod, "run_cell_job", noop_job)

    from app.main import app
    return TestClient(app)


@pytest.mark.asyncio
async def test_synthesize_builds_matrix_and_calls_llm(client, monkeypatch):
    # The service layer uses `engine` imported into its own namespace at
    # import-time, which diverges from the per-test tmp DB when tests run in
    # a batch. Point every consumer at the fresh `db.engine` first.
    from app.storage import db as db_mod
    from app.services import synthesize as syn_mod
    from app.api import routes as routes_mod
    monkeypatch.setattr(syn_mod, "engine", db_mod.engine)
    monkeypatch.setattr(routes_mod, "engine", db_mod.engine)

    # Seed a workspace/grid/row/column/cell directly on the live engine
    # so the test doesn't depend on route-layer engine binding.
    from app.storage.models import Workspace, Grid, Document, Row, Cell, Column
    from sqlmodel import select
    with Session(db_mod.engine) as s:
        ws = Workspace(name="w"); s.add(ws); s.commit(); s.refresh(ws)
        g = Grid(workspace_id=ws.id, name="g", retriever_mode="naive")
        s.add(g); s.commit(); s.refresh(g)
        d = Document(workspace_id=ws.id, filename="a.pdf", sha256="x" * 16, status="ready")
        s.add(d); s.commit(); s.refresh(d)
        row = Row(grid_id=g.id, document_id=d.id, position=0)
        s.add(row); s.commit(); s.refresh(row)
        col = Column(grid_id=g.id, position=0, prompt="Revenue YoY",
                     shape_hint="percentage", version=1)
        s.add(col); s.commit(); s.refresh(col)
        cell = Cell(grid_id=g.id, row_id=row.id, column_id=col.id,
                    column_version=1, status="done",
                    answer_json={"value": "2.8%", "shape": "percentage"})
        s.add(cell); s.commit(); s.refresh(cell)
        grid_id = g.id

    # sanity: cell should be visible to the same engine the service uses
    with Session(db_mod.engine) as s:
        cell_list = list(s.exec(select(Cell)).all())
        assert cell_list, "cell should be persisted"

    # stub llm.chat to capture the prompt and return a canned synthesis
    calls = {"n": 0, "prompt": ""}
    async def fake_chat(messages, **kw):
        calls["n"] += 1
        calls["prompt"] = messages[0]["content"]
        return "Synthesis: Apple showed 2.8% YoY growth."
    monkeypatch.setattr(syn_mod.llm, "chat", fake_chat)

    resp = client.post(f"/api/grids/{grid_id}/synthesize",
                       json={"prompt": "Summarise growth across issuers."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"].startswith("Synthesis:")
    assert "Revenue YoY" in calls["prompt"]   # matrix table rendered into prompt
    assert "2.8%" in calls["prompt"]
    assert calls["n"] == 1
