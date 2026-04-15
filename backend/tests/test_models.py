def test_create_grid_and_cell(tmp_path, monkeypatch):
    from app import settings as s
    monkeypatch.setattr(s.settings, "storage_root", tmp_path)
    s.settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    from app.storage import db as db_mod
    db_mod.init_db(reset=True)
    from app.storage.models import Workspace, Document, Grid, Column, Row, Cell
    from sqlmodel import Session, select
    with Session(db_mod.engine) as sess:
        w = Workspace(name="w"); sess.add(w); sess.commit(); sess.refresh(w)
        d = Document(workspace_id=w.id, filename="a.pdf", sha256="x", status="ready")
        g = Grid(workspace_id=w.id, name="g", retriever_mode="naive")
        sess.add_all([d, g]); sess.commit(); sess.refresh(d); sess.refresh(g)
        col = Column(grid_id=g.id, position=0, prompt="Q", shape_hint="text", version=1)
        row = Row(grid_id=g.id, document_id=d.id, position=0)
        sess.add_all([col, row]); sess.commit(); sess.refresh(col); sess.refresh(row)
        cell = Cell(grid_id=g.id, row_id=row.id, column_id=col.id,
                    column_version=1, status="idle")
        sess.add(cell); sess.commit()
        got = sess.exec(select(Cell)).all()
        assert len(got) == 1 and got[0].status == "idle"
