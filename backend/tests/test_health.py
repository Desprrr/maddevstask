from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    # Без "with" — TestClient как контекст-менеджер запускает настоящий
    # app-lifespan (планировщик и т.д. против БД из настроек, не тестовой);
    # /health не зависит ни от какого lifespan-состояния, так что обычный
    # запрос без входа в контекст безопаснее и не трогает прод-БД.
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
