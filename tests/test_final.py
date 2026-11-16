"""The final survey (app/final.py) against an in-memory Mongo."""
import asyncio
import random

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import db as dbmod
from app import final
from app import main


def _manifest(n_prompts=30, n_core=4):
    clips, pairs = [], []
    for p in range(n_prompts):
        a, b = f"b{p:02d}", f"e{p:02d}"
        for c in (a, b):
            clips.append({"clip_id": c, "prompt_key": f"p{p:02d}", "prompt_text": f"do {p}",
                          "prompt_text_he": "he", "prompt_text_ru": "ru", "file": f"final/clips/{c}.mp4",
                          "image_file": f"final/images/i{p:02d}.jpg"})
        pairs.append({"pair_id": f"p{p:02d}", "a": a, "b": b, "prompt_key": f"p{p:02d}",
                      "legs": {a: "base", b: "ext"}, "core": p < n_core})
    return clips, pairs


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture
def client():
    from starlette.testclient import TestClient

    db = AsyncMongoMockClient()["survey"]
    dbmod.set_db(db)
    clips, pairs = _manifest()
    _run(db.final_clips.insert_many(clips))
    _run(db.final_pairs.insert_many(pairs))
    with TestClient(main.app) as c:
        c.db = db
        yield c


def test_pick_round_core_then_fewest_answers():
    _, pairs = _manifest()
    out = final.pick_round(pairs, {}, set(), random.Random(0))
    assert len(out) == final.N_ROUND and len({p["prompt_key"] for p in out}) == final.N_ROUND
    assert sum(p["core"] for p in out) == final.N_CORE and out[0]["core"] and out[1]["core"]
    # among the others, unanswered pairs come before answered ones
    counts = {p["pair_id"]: 3 for p in pairs[4:20]}
    out = final.pick_round(pairs, counts, set(), random.Random(0))
    assert all(counts.get(p["pair_id"], 0) == 0 for p in out if not p["core"])


def test_pick_round_core_exhausted_and_fill():
    _, pairs = _manifest(n_prompts=10, n_core=4)
    core = {p["pair_id"] for p in pairs if p["core"]}
    out = final.pick_round(pairs, {}, core, random.Random(0))
    assert len(out) == 6 and not any(p["core"] for p in out)   # only 6 others exist
    others = {p["pair_id"] for p in pairs if not p["core"]}
    out = final.pick_round(pairs, {}, others, random.Random(0))
    assert len(out) == 4 and all(p["core"] for p in out)        # the rest of the core fills the round


def test_round_hides_legs_and_answer_stores_leg(client):
    r = client.get("/api/final/round", params={"rater": "r1"}).json()
    assert len(r["items"]) == 8 and r["left"] == 30 - 8
    for it in r["items"]:
        assert "legs" not in it and "core" not in it
    it = r["items"][0]
    ok = client.post("/api/final/answer", json={"pair_id": it["pair_id"], "first": it["first"], "second": it["second"],
                                                "choice": "first", "elapsed_ms": 900, "rater_id": "r1", "src": "fam"})
    assert ok.status_code == 200
    doc = _run(client.db.final_answers.find_one({"rater_id": "r1"}))
    assert doc["better"] == it["first"] and doc["src"] == "fam"
    assert doc["better_leg"] == ("base" if it["first"].startswith("b") else "ext")
    same = client.post("/api/final/answer", json={"pair_id": it["pair_id"], "first": it["first"], "second": it["second"],
                                                  "choice": "same", "elapsed_ms": 900, "rater_id": "r1"})
    assert same.status_code == 200
    docs = _run(client.db.final_answers.find({"rater_id": "r1"}).to_list(10))
    assert len(docs) == 1 and docs[0]["better_leg"] is None   # de-duped, the later answer stands
    # the next round never repeats an answered pair
    r2 = client.get("/api/final/round", params={"rater": "r1"}).json()
    assert it["pair_id"] not in {x["pair_id"] for x in r2["items"]}


def test_answer_rejects_foreign_clip(client):
    bad = client.post("/api/final/answer", json={"pair_id": "p00", "first": "b00", "second": "e01",
                                                 "choice": "first", "elapsed_ms": 1})
    assert bad.status_code == 400
