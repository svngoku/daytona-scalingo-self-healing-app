from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

source = Path(__file__).resolve().parents[1] / "main.py"
spec = spec_from_file_location("demo_pricing", source)
assert spec is not None and spec.loader is not None
pricing = module_from_spec(spec)
spec.loader.exec_module(pricing)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "pricing.jsonl"))
    with TestClient(pricing.app) as http:
        yield http


def test_health(client):
    response = client.get("/health", headers={"X-Correlation-ID": "health-check"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Correlation-ID"] == "health-check"


def test_positive_quantity_returns_quote(client):
    response = client.get("/api/quote", params={"quantity": 5})

    assert response.status_code == 200
    assert response.json() == {
        "quantity": 5,
        "unit_price": 25,
        "total": 125,
        "discount_per_item": 2.0,
    }


def test_zero_quantity_returns_400(client):
    response = client.get("/api/quote", params={"quantity": 0})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "quantity" in detail.lower()
