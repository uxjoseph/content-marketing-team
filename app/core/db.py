from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlmodel import SQLModel, Session, create_engine

_engine = None


def init_engine(database_url: str) -> None:
    global _engine
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, connect_args=connect_args)


def get_engine():
    if _engine is None:
        raise RuntimeError("Database engine is not initialized.")
    return _engine


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
