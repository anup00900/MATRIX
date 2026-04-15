from sqlmodel import SQLModel, create_engine
from ..settings import settings


def _make_engine():
    return create_engine(
        f"sqlite:///{settings.db_path}",
        connect_args={"check_same_thread": False},
    )


engine = _make_engine()


def init_db(reset: bool = False) -> None:
    global engine
    if reset and settings.db_path.exists():
        settings.db_path.unlink()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = _make_engine()
    from . import models  # noqa: F401 - register tables
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
