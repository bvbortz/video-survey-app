"""The 2026-08 changes: comparison-only blocks, subgroup quota, consent stamp.

These guard three things that are easy to break silently and expensive to notice
late: a rater asking for comparisons must never be handed a rating form, a
verdict must carry the stratum it was sampled from, and the quota must actually
oversample the two pre-registered subgroups rather than sampling in proportion
to the pool.
"""
import asyncio

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import db as dbmod
from app import main
from app.assignment import build_session_items, subgroup_of


def _pair(pid, mode, origin=None, misleading=False):
    """A base_vs_finetuned pair with distinct clips, so dedup never blocks it."""
    arm = "base_vs_finetuned" if mode == "2afc" else "short_vs_finetuned"
    a, b = ("base", "finetuned") if mode == "2afc" else ("short", "finetuned")
    return {
        "pair_id": pid, "generator": "ltx2", "version": "v1", "prompt_id": pid,
        "arm": arm, "mode": mode, "prompt_text": f"do thing {pid}",
        "image_file": "img.png", "is_attention_check": False,
        "origin": origin, "misleading": misleading,
        "legs": [
            {"leg": a, "clip_id": f"{pid}_{a}", "file": f"{pid}_{a}.mp4", "auto_score": 0.4},
            {"leg": b, "clip_id": f"{pid}_{b}", "file": f"{pid}_{b}.mp4", "auto_score": 0.6},
        ],
    }


def _mkdb():
    db = AsyncMongoMockClient()["survey"]
    pairs = []
    # Pool shaped like the real one: subgroups are the minority, so proportional
    # sampling would rarely pick them and a quota is observable.
    for i in range(40):
        pairs.append(_pair(f"oth{i:02d}", "2afc", origin="kept"))
    for i in range(12):
        pairs.append(_pair(f"ind{i:02d}", "2afc", origin="indirect"))
    for i in range(12):
        pairs.append(_pair(f"mis{i:02d}", "2afc", origin="authored", misleading=True))
    for i in range(20):
        pairs.append(_pair(f"rat{i:02d}", "mos", origin="kept"))
    asyncio.get_event_loop().run_until_complete(db.pairs.insert_many(pairs))
    return db


def test_subgroup_of_is_disjoint_and_prefers_indirect():
    # The two populations are disjoint in the data; if one ever did carry both
    # flags, it must land in exactly one bucket, not be counted twice.
    assert subgroup_of({"origin": "indirect"}) == "indirect"
    assert subgroup_of({"origin": "authored", "misleading": True}) == "misleading"
    assert subgroup_of({"origin": "kept"}) == "other"
    assert subgroup_of({"origin": "indirect", "misleading": True}) == "indirect"


def test_choice_block_is_comparisons_only():
    db = _mkdb()
    items = asyncio.get_event_loop().run_until_complete(
        build_session_items(db, block="choice"))
    assert items, "choice block returned nothing"
    assert all(it["pair"]["mode"] == "2afc" for it in items), \
        "a rater who asked for comparisons was handed a rating pair"


def test_rating_block_is_ratings_only():
    db = _mkdb()
    items = asyncio.get_event_loop().run_until_complete(
        build_session_items(db, block="rating"))
    assert items
    assert all(it["pair"].get("mode") != "2afc" for it in items)


def test_quota_oversamples_the_pre_registered_subgroups():
    """Averaged over sessions, the subgroups must beat their pool share."""
    db = _mkdb()
    loop = asyncio.get_event_loop()
    counts = {"indirect": 0, "misleading": 0, "other": 0}
    runs = 40
    for _ in range(runs):
        items = loop.run_until_complete(build_session_items(db, block="choice"))
        for it in items:
            counts[it["subgroup"]] += 1
    total = sum(counts.values())
    assert total > 0
    share = {k: v / total for k, v in counts.items()}
    # Pool share of each subgroup is 12/64 = 19%; the quota asks for 40% each.
    # Assert clearly above the pool share, well below the exact quota, so the
    # test survives cascade effects without becoming vacuous.
    assert share["indirect"] > 0.28, share
    assert share["misleading"] > 0.28, share
    # `other` must not be starved to zero — the pooled estimate still needs it.
    assert counts["other"] > 0, share


def test_session_records_subgroup_on_the_response(monkeypatch):
    from starlette.testclient import TestClient

    db = _mkdb()
    dbmod.set_db(db)
    monkeypatch.setattr(main, "VIDEO_BASE_URL", "https://cdn.example/videos")
    with TestClient(main.app) as c:
        s = c.get("/api/session?block=choice").json()
        assert all(i["mode"] == "2afc" for i in s["items"])

        r = c.post("/api/response", json={
            "session_id": s["session_id"], "index": 0,
            "choice": "A", "elapsed_ms": 1234,
        })
        assert r.status_code == 200, r.text

        doc = asyncio.get_event_loop().run_until_complete(
            db.responses.find_one({"session_id": s["session_id"], "index": 0}))
        assert doc is not None
        assert doc["subgroup"] in ("indirect", "misleading", "other"), doc
        assert doc["mode"] == "2afc"


def test_consent_stamp_separates_bounce_from_abandon(monkeypatch):
    from starlette.testclient import TestClient

    db = _mkdb()
    dbmod.set_db(db)
    monkeypatch.setattr(main, "VIDEO_BASE_URL", "https://cdn.example/videos")
    loop = asyncio.get_event_loop()
    with TestClient(main.app) as c:
        s = c.get("/api/session").json()
        sid = s["session_id"]
        # Created on page load, before consent — must NOT be stamped yet.
        doc = loop.run_until_complete(db.sessions.find_one({"session_id": sid}))
        assert doc.get("consented_at") is None

        assert c.post(f"/api/session/{sid}/consent").status_code == 200
        doc = loop.run_until_complete(db.sessions.find_one({"session_id": sid}))
        assert doc.get("consented_at") is not None

    # An unknown session must not blow up — it is a best-effort beacon.
    with TestClient(main.app) as c:
        assert c.post("/api/session/does-not-exist/consent").status_code == 200


def test_unknown_block_falls_back_to_a_normal_session(monkeypatch):
    """An old cached client sending garbage must still get a usable session."""
    from starlette.testclient import TestClient

    db = _mkdb()
    dbmod.set_db(db)
    monkeypatch.setattr(main, "VIDEO_BASE_URL", "https://cdn.example/videos")
    with TestClient(main.app) as c:
        s = c.get("/api/session?block=nonsense").json()
        assert s["items"], "a bad block value locked the rater out"
