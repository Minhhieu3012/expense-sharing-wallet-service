from unittest.mock import patch 

from fastapi.testclient import TestClient 

from app.main import app 

client = TestClient(app)

def test_health_returns_200_when_all_dependencies_are_up() -> None: 
    # Arrage
    with (
        patch("app.main.check_db_connection", return_value = True),
        patch("app.main.check_redis_connection", return_value = True),
    ):
        # Act 
        response = client.get("/health")

    # Assert 
    assert response.status_code == 200 
    assert response.json() == {
        "status": "ok",
        "dependencies": {
            "postgresql": "up",
            "redis": "up",
        },
    }

def test_health_returns_503_when_database_is_down() -> None: 
    # Arrange
    with(
        patch("app.main.check_db_connection", return_value = False),
        patch("app.main.check_redis_connection", return_value=True),
    ):
        # Act 
        response = client.get("/health")

    # Assert
    assert response.status_code == 503 
    assert response.json() == {
        "status": "degraded",
        "dependencies": {
            "postgresql": "down",
            "redis": "up",
        },
    }

def test_health_returns_503_when_redis_is_down() -> None: 
    # Arrange
    with(
        patch("app.main.check_db_connection", return_value = True),
        patch("app.main.check_redis_connection", return_value=False),
    ):
        # Act 
        response = client.get("/health")

    # Assert
    assert response.status_code == 503 
    assert response.json() == {
        "status": "degraded",
        "dependencies": {
            "postgresql": "up",
            "redis": "down",
        },
    }