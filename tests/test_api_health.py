"""Health / readiness endpoint tests."""
from __future__ import annotations


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True


def test_ready(client):
    resp = client.get("/api/ready")
    assert resp.status_code == 200


def test_system_version_matches_frontend_route(client, monkeypatch):
    monkeypatch.setattr("api.system._fetch_latest_release", lambda: None)
    resp = client.get("/api/system/version")
    assert resp.status_code == 200
    assert resp.json()["has_update"] is False
