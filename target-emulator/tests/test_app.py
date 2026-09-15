from fastapi.testclient import TestClient

from app import app


def test_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/ok")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_code_passthrough() -> None:
    with TestClient(app) as client:
        response = client.get("/status/503")
    assert response.status_code == 503


def test_delay_returns_after_sleep() -> None:
    with TestClient(app) as client:
        response = client.get("/delay/10")
    assert response.status_code == 200
    assert response.json() == {"delayed_ms": 10}


def test_flaky_zero_percent_never_fails() -> None:
    with TestClient(app) as client:
        response = client.get("/flaky/0")
    assert response.status_code == 200


def test_flaky_hundred_percent_always_fails() -> None:
    with TestClient(app) as client:
        response = client.get("/flaky/100")
    assert response.status_code == 500
