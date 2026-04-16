import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import settings as s_mod
    monkeypatch.setattr(s_mod.settings, "storage_root", tmp_path)
    (s_mod.settings.db_path.parent).mkdir(parents=True, exist_ok=True)
    for d in (s_mod.settings.pdfs_dir, s_mod.settings.parsed_dir,
              s_mod.settings.wikis_dir, s_mod.settings.vectors_dir,
              s_mod.settings.traces_dir):
        d.mkdir(parents=True, exist_ok=True)

    from app.storage import db as db_mod
    db_mod.init_db(reset=True)

    # Neutralise background cell jobs so tests don't block on LLM
    from app.services import cells as cells_mod
    async def noop_job(*, cell_id: str): return None
    monkeypatch.setattr(cells_mod, "run_cell_job", noop_job)
    # route imports the name; patch its binding too
    from app.api import routes as routes_mod
    monkeypatch.setattr(routes_mod, "run_cell_job", noop_job)

    from app.main import app
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_workspace_and_grid_crud_and_stale(client):
    w = client.post("/api/workspaces", json={"name": "demo"}).json()
    assert w["id"]
    g = client.post("/api/grids", json={
        "workspace_id": w["id"], "name": "g", "retriever_mode": "naive",
    }).json()
    assert g["id"] and g["retriever_mode"] == "naive"

    col = client.post(f"/api/grids/{g['id']}/columns", json={
        "prompt": "Revenue YoY", "shape_hint": "percentage",
    }).json()
    assert col["id"] and col["version"] == 1

    # PATCH retriever
    g2 = client.patch(f"/api/grids/{g['id']}", json={"retriever_mode": "isd"}).json()
    assert g2["retriever_mode"] == "isd"

    # PATCH column bumps version and marks cells stale (though none yet)
    col2 = client.patch(f"/api/columns/{col['id']}", json={
        "prompt": "Revenue YoY change",
    }).json()
    assert col2["version"] == 2

    # GET grid
    view = client.get(f"/api/grids/{g['id']}").json()
    assert view["grid"]["id"] == g["id"]
    assert len(view["columns"]) == 1
