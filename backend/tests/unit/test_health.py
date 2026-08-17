from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200


def test_ready():
    response = client.get("/ready")

    assert response.status_code == 200