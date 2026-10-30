"""Which Clip Is Better (app/compare.py) against an in-memory Mongo."""
import asyncio
import itertools
import random

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import compare
from app import db as dbmod
from app import main


def _clips(n_prompts=12, per=3):
    return [{"clip_id": f"c{p:02d}{k}", "prompt_key": f"p{p:02d}", "prompt_text": f"do {p}",
             "prompt_text_he": None, "file": f"check/clips/c{p:02d}{k}.mp4",
             "image_file": f"check/images/i{p:02d}.jpg"} for p in range(n_prompts) for k in "abc"[:per]]


def _pairs(clips, tier1=("p00", "p01")):
    by = {}
    for c in clips:
        by.setdefault(c["prompt_key"], []).append(c["clip_id"])
    return [{"pair_id": f"{a}-{b}", "a": a, "b": b, "prompt_key": pk, "tier": 1 if pk in tier1 else 2}
            for pk, ids in by.items() for a, b in itertools.combinations(ids, 2)]


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture
def client():
    from starlette.testclient import TestClient

    db = AsyncMongoMockClient()["survey"]
    dbmod.set_db(db)
    clips = _clips()
    _run(db.check_clips.insert_many(clips))
    _run(db.check_pairs.insert_many(_pairs(clips)))
    with TestClient(main.app) as c:
        yield c


def test_pick_round_tier1_first_until_target():
    pairs = _pairs(_clips())
    out = compare.pick_round(pairs, {}, set(), random.Random(0))
    assert len(out) == 10 and len({p["prompt_key"] for p in out}) == 10
    assert {p["prompt_key"] for p in out if p["tier"] == 1} == {"p00", "p01"}
    # tier-1 pairs at target fall behind unanswered tier-2 pairs
    full = {p["pair_id"]: compare.TARGET for p in pairs if p["tier"] == 1}
    out = compare.pick_round(pairs, full, set(), random.Random(0))
    assert all(p["tier"] == 2 for p in out)


def test_pick_round_new_prompts_before_tier():
    """a second round gives fresh prompts before more tier-1 pairs of prompts already seen"""
    pairs = _pairs(_clips())
    first = compare.pick_round(pairs, {}, set(), random.Random(0))
    seen = {p["pair_id"] for p in first}
    second = compare.pick_round(pairs, {}, seen, random.Random(1))
    fresh = {p["prompt_key"] for p in second} - {p["prompt_key"] for p in first}
    assert len(fresh) == 2   # the only 2 of 12 prompts round 1 did not use
    # the repeated prompts get a pair with as few watched clips as there is (1 of 2 here)
    watched = {c for p in first for c in (p["a"], p["b"])}
    for p in second:
        if p["prompt_key"] not in fresh:
            assert (p["a"] in watched) + (p["b"] in watched) == 1


def test_round_answer_dedupe_and_no_repeat(client):
    r = client.get("/api/compare/round", params={"rater": "r1"}).json()
    assert len(r["items"]) == 10 and r["left"] == 36 - 10
    it = r["items"][0]
    assert {it["first"], it["second"]} == set(it["pair_id"].split("-"))
    assert it["first_url"].endswith(f"{it['first']}.mp4") and it["second_url"].endswith(f"{it['second']}.mp4")
    for x in r["items"]:
        ok = client.post("/api/compare/answer", json={"pair_id": x["pair_id"], "first": x["first"],
                                                      "second": x["second"], "choice": "first",
                                                      "elapsed_ms": 1000, "rater_id": "r1"})
        assert ok.status_code == 200
    client.post("/api/compare/answer", json={"pair_id": it["pair_id"], "first": it["first"], "second": it["second"],
                                             "choice": "same", "elapsed_ms": 900, "rater_id": "r1",
                                             "prompt_flag": True})
    r2 = client.get("/api/compare/round", params={"rater": "r1"}).json()
    assert not {i["pair_id"] for i in r2["items"]} & {i["pair_id"] for i in r["items"]}
    db = dbmod.get_db()
    assert _run(db.compare_answers.count_documents({"rater_id": "r1"})) == 10
    doc = _run(db.compare_answers.find_one({"pair_id": r["items"][1]["pair_id"]}))
    assert doc["better"] == r["items"][1]["first"]
    redone = _run(db.compare_answers.find_one({"pair_id": it["pair_id"]}))
    assert redone["better"] is None and redone["prompt_flag"] is True
    assert doc["prompt_flag"] is False


def test_retired_clip_drops_its_pairs(client):
    db = dbmod.get_db()
    _run(db.check_clips.update_one({"clip_id": "c00a"}, {"$set": {"active": False}}))
    for _ in range(5):
        r = client.get("/api/compare/round").json()
        assert all("c00a" not in i["pair_id"] for i in r["items"])


def test_bad_choice_and_wrong_clips(client):
    assert client.post("/api/compare/answer", json={"pair_id": "c00a-c00b", "first": "c00a", "second": "c00b",
                                                    "choice": "left", "elapsed_ms": 1}).status_code == 422
    assert client.post("/api/compare/answer", json={"pair_id": "c00a-c00b", "first": "c00a", "second": "c01a",
                                                    "choice": "first", "elapsed_ms": 1}).status_code == 400


def test_page_served_and_admin_gated(client):
    assert client.get("/compare").status_code == 200
    assert client.get("/admin/compare").status_code == 401
    assert client.get("/admin/compare/export").status_code == 401
