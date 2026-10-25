from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.seed import seed

FIXTURES = Path(__file__).parent / "fixtures" / "bncap"


@pytest.fixture(scope="session")
def html():
    """name -> raw saved page, e.g. html['dzire']"""
    return {p.stem: p.read_text(encoding="utf-8") for p in FIXTURES.glob("*.html")}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as s:
        seed(s)
        yield s


@pytest.fixture()
def api(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()
