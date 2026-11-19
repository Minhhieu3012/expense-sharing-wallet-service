from fastapi.testclient import TestClient 

from app.main import app 

client = TestClient(app)

def test_health_endpoint_connects_to_real_postgres_and_redis() -> None:
    # Arrage & Act (yeu cau docker compose run va healthy)
    response = client.get("/health")

    # Assert 
    assert response.status_code == 200 
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["postgresql"] == "up"
    assert body["dependencies"]["redis"] == "up"