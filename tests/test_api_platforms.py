"""Platform listing endpoint tests."""
from __future__ import annotations


def test_list_platforms(client):
    resp = client.get("/api/platforms")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    names = [p["name"] for p in data]
    # At least the core platforms should be loaded
    assert "chatgpt" in names
    assert "cursor" in names


def test_platform_has_required_fields(client):
    resp = client.get("/api/platforms")
    data = resp.json()
    for platform in data:
        assert "name" in platform
        assert "display_name" in platform
        assert "version" in platform
        assert "supported_executors" in platform
        assert isinstance(platform["supported_executors"], list)


def test_chatgpt_exposes_protocol_registration(client):
    platforms = client.get("/api/platforms").json()
    chatgpt = next(item for item in platforms if item["name"] == "chatgpt")
    assert "protocol" in chatgpt["supported_executors"]
