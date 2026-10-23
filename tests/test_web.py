from fastapi.testclient import TestClient

from app.main import app


def test_health_is_ok():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "smartphone" in body["config"]["categories"]


def test_home_page_renders():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "FlipScore" in response.text


def test_health_reports_broken_database(monkeypatch):
    from app.core.settings import get_settings
    from app.db.session import get_engine

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1:1/none")
    get_settings.cache_clear()
    get_engine.cache_clear()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"]["ok"] is False
