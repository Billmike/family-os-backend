import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Disable scheduler side effects during import
os.environ["JWT_SECRET"] = "test-secret"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ENVIRONMENT"] = "test"

from app.core.database import Base, get_db
from app.main import app as fastapi_app
from app.workers.reminders import stop_scheduler
import app.models  # noqa: F401


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = override_get_db
    stop_scheduler()
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()
    stop_scheduler()


def auth_headers(client: TestClient, email: str, password: str = "password123", name: str = "User") -> dict:
    reg = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": name},
    )
    assert reg.status_code == 200, reg.text
    token = reg.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
