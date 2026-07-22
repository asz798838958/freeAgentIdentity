"""
Tests for the BitBrowser profile pool (application.bitbrowser_profiles).

We only verify the behavior end-users care about:
    * acquire returns the least-used profile, then increments usage
    * release decrements usage, and the next acquire prefers it again
    * empty pool raises BitBrowserProfilePoolEmpty (acquire) or returns
      fallback (acquire_or)
    * add / remove / replace_all round-trip through the persisted store

The persisted store is stubbed via monkeypatch so tests stay
in-memory and never touch the real SQLite DB.
"""

from __future__ import annotations

import pytest

from application import bitbrowser_profiles as bp


@pytest.fixture
def pool(monkeypatch):
    """Fresh pool with an in-memory store stub (no SQLite touch)."""
    state: dict[str, str] = {}

    class _StubStore:
        def get(self, key, default=""):
            return state.get(key, default)

        def set(self, key, value):
            state[key] = value

    monkeypatch.setattr(bp, "config_store", _StubStore())
    return bp.BitBrowserProfilePool()


def test_add_persists_and_lists(pool):
    assert pool.add("p1") is True
    assert pool.add("p2") is True
    # duplicate returns False but does not raise
    assert pool.add("p1") is False
    items = pool.list_profiles()
    assert [it["profile_id"] for it in items] == ["p1", "p2"]
    assert all(it["in_use"] == 0 for it in items)


def test_remove_returns_true_only_when_present(pool):
    pool.add("p1")
    assert pool.remove("p1") is True
    assert pool.remove("p1") is False
    assert pool.list_profiles() == []


def test_acquire_picks_least_used_and_increments(pool):
    pool.add("p1")
    pool.add("p2")
    pool.add("p3")

    # First three acquires must each return a different profile (usage 0 → 1).
    first = {pool.acquire(), pool.acquire(), pool.acquire()}
    assert first == {"p1", "p2", "p3"}

    # Fourth acquire must reuse some profile (all are at usage=1 now).
    fourth = pool.acquire()
    assert fourth in {"p1", "p2", "p3"}
    counts = {it["profile_id"]: it["in_use"] for it in pool.list_profiles()}
    assert counts[fourth] == 2
    # Other two stay at 1
    others = [v for k, v in counts.items() if k != fourth]
    assert sorted(others) == [1, 1]


def test_release_brings_profile_back_to_top_of_queue(pool):
    pool.add("p1")
    pool.add("p2")

    a = pool.acquire()
    b = pool.acquire()
    assert {a, b} == {"p1", "p2"}

    # Release p1; next acquire must prefer p1 again (least used)
    pool.release(a)
    third = pool.acquire()
    assert third == a


def test_acquire_empty_pool_raises(pool):
    with pytest.raises(bp.BitBrowserProfilePoolEmpty):
        pool.acquire()


def test_acquire_or_returns_fallback_when_pool_empty(pool):
    assert pool.acquire_or(fallback="env-pid") == "env-pid"


def test_acquire_or_uses_pool_when_not_empty(pool):
    pool.add("p1")
    assert pool.acquire_or(fallback="env-pid") == "p1"


def test_acquire_profile_for_browser_mode_uses_pool_and_release(pool, monkeypatch):
    monkeypatch.setattr(bp, "bitbrowser_profile_pool", pool)
    pool.add("p1")

    profile_id, acquired_id = bp.acquire_profile_for_browser_mode("bitbrowser_hidden")

    assert profile_id == "p1"
    assert acquired_id == "p1"
    assert pool.list_profiles()[0]["in_use"] == 1

    bp.release_acquired_profile(acquired_id)

    assert pool.list_profiles()[0]["in_use"] == 0


def test_acquire_profile_for_browser_mode_ignores_camoufox(pool, monkeypatch):
    monkeypatch.setattr(bp, "bitbrowser_profile_pool", pool)

    assert bp.acquire_profile_for_browser_mode("camoufox_headed") == ("", "")


def test_replace_all_overwrites_pool(pool):
    pool.add("old1")
    pool.add("old2")
    final = pool.replace_all(["new1", "new2", "new3"])
    assert final == ["new1", "new2", "new3"]
    assert [it["profile_id"] for it in pool.list_profiles()] == [
        "new1",
        "new2",
        "new3",
    ]


def test_persisted_store_tolerates_comma_or_semicolon_separators(monkeypatch):
    """
    Users sometimes paste comma-separated lists. We accept them too as long
    as the values look like profile IDs.
    """
    state = {"bitbrowser_profile_pool": "p1,p2;p3\np4"}

    class _StubStore:
        def get(self, key, default=""):
            return state.get(key, default)

        def set(self, key, value):
            state[key] = value

    monkeypatch.setattr(bp, "config_store", _StubStore())
    pool = bp.BitBrowserProfilePool()
    items = [it["profile_id"] for it in pool.list_profiles()]
    assert items == ["p1", "p2", "p3", "p4"]


def test_comments_and_blank_lines_are_ignored(monkeypatch):
    state = {"bitbrowser_profile_pool": "p1\n\n# this is a comment\np2\n   "}

    class _StubStore:
        def get(self, key, default=""):
            return state.get(key, default)

        def set(self, key, value):
            state[key] = value

    monkeypatch.setattr(bp, "config_store", _StubStore())
    pool = bp.BitBrowserProfilePool()
    items = [it["profile_id"] for it in pool.list_profiles()]
    assert items == ["p1", "p2"]
