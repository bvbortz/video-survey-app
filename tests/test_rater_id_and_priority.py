"""The 2026-08-24 changes: pseudonymous rater ids, and priority-weighted pairs.

Both exist to make rater-level statistics possible. Sessions alone cannot support
them -- a returning respondent starts a new session and reads as a second person,
so nothing links their verdicts -- and verdicts spread evenly over the whole pool
give one judgement per pair, so no two people ever grade the same thing.

What is guarded here: a rater id survives onto the stored verdict, its absence is
never fatal, priority pairs are genuinely favoured, and -- the one that would be
expensive to discover late -- the boost is a bias and not a filter, so the pool
does not collapse to 50 pairs and strand a returning rater.
"""
import asyncio
from collections import Counter

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import db as dbmod
from app import main
from app.assignment import build_session_items, _is_priority


def _pair(pid, priority=None):
    p = {
        "pair_id": pid, "generator": "ltx2", "version": "v1", "prompt_id": pid,
        "arm": "base_vs_finetuned", "mode": "2afc", "prompt_text": f"do {pid}",
        "image_file": f"{pid}.png", "is_attention_check": False, "origin": "kept",
        "legs": [
            {"leg": "base", "clip_id": f"{pid}_b", "file": f"{pid}_b.mp4"},
            {"leg": "finetuned", "clip_id": f"{pid}_f", "file": f"{pid}_f.mp4"},
        ],
    }
    if priority is not None:
        p["priority"] = priority
    return p


def _mkdb(n_priority=10, n_plain=90):
    db = AsyncMongoMockClient()["survey"]
    pairs = [_pair(f"pri{i:02d}", True) for i in range(n_priority)]
    pairs += [_pair(f"pln{i:02d}") for i in range(n_plain)]
    asyncio.get_event_loop().run_until_complete(db.pairs.insert_many(pairs))
    return db


def test_string_booleans_are_not_all_true():
    """The loader writes "True"/"False" as strings; "False" must not read true."""
    assert _is_priority({"priority": True})
    assert _is_priority({"priority": "True"})
    assert not _is_priority({"priority": "False"})
    assert not _is_priority({"priority": False})
    assert not _is_priority({})


def test_priority_pairs_are_favoured():
    db = _mkdb()
    seen = Counter()
    for _ in range(40):
        items = asyncio.get_event_loop().run_until_complete(
            build_session_items(db, block="choice"))
        for it in items:
            seen[it["pair_id"].startswith("pri")] += 1
    total = sum(seen.values())
    assert total, "sessions produced no items"
    # 10 of 100 pairs are priority. Proportional sampling would put them near
    # 10%; the boost should lift them far above that.
    assert seen[True] / total > 0.4, f"priority share only {seen[True]/total:.2f}"


def test_priority_is_a_bias_not_a_filter():
    """A rater who exhausted every priority pair still gets a full session.

    This is the failure that would matter in production: if the boost acted as a
    filter, a returning respondent would hit `exhausted` after ~50 pairs and be
    turned away while hundreds remain unrated.
    """
    db = _mkdb()
    from app.assignment import pair_token
    seen_tokens = {pair_token(f"pri{i:02d}") for i in range(10)}
    items = asyncio.get_event_loop().run_until_complete(
        build_session_items(db, seen_tokens=seen_tokens, block="choice"))
    assert items, "pool collapsed once priority pairs were used up"
    assert all(not it["pair_id"].startswith("pri") for it in items)


def _client(db):
    dbmod._db = db
    from starlette.testclient import TestClient
    return TestClient(main.app)


def test_rater_id_reaches_the_stored_verdict():
    db = _mkdb()
    c = _client(db)
    r = c.get("/api/session?block=choice&rater=rater-abc")
    s = r.json()
    assert s["session_id"]
    c.post("/api/response", json={
        "session_id": s["session_id"], "index": 0, "elapsed_ms": 1234,
        "choice": "A", "rater_id": "rater-abc",
    })
    docs = asyncio.get_event_loop().run_until_complete(
        db.responses.find({}).to_list(length=10))
    assert docs and docs[0]["rater_id"] == "rater-abc"
    sess = asyncio.get_event_loop().run_until_complete(
        db.sessions.find_one({"session_id": s["session_id"]}))
    assert sess["rater_id"] == "rater-abc"


def test_missing_rater_id_is_not_fatal():
    """Storage can be blocked. That costs one datum, never the verdicts."""
    db = _mkdb()
    c = _client(db)
    s = c.get("/api/session?block=choice").json()
    assert s["session_id"]
    r = c.post("/api/response", json={
        "session_id": s["session_id"], "index": 0, "elapsed_ms": 10,
        "choice": "tie",
    })
    assert r.status_code == 200
    docs = asyncio.get_event_loop().run_until_complete(
        db.responses.find({}).to_list(length=10))
    assert docs and docs[0]["rater_id"] is None
