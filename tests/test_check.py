"""Ten Clip Check (app/check.py) against an in-memory Mongo."""
import random

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import check
from app import db as dbmod
from app import main


def _clips(n_prompts=14, per=3):
    return [{"clip_id": f"c{p:02d}{k}", "prompt_key": f"p{p:02d}", "prompt_text": f"do {p}",
             "prompt_text_he": None, "file": f"check/clips/c{p:02d}{k}.mp4",
             "image_file": f"check/images/i{p:02d}.jpg"} for p in range(n_prompts) for k in "abc"[:per]]


@pytest.fixture
def client():
    from starlette.testclient import TestClient

    db = AsyncMongoMockClient()["survey"]
    dbmod.set_db(db)
    import asyncio
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(db.check_clips.insert_many(_clips()))
    with TestClient(main.app) as c:
        yield c


def test_pick_round_one_per_prompt_least_answered_first():
    clips = _clips()
    counts = {c["clip_id"]: 1 for c in clips if c["clip_id"].endswith("a")}
    out = check.pick_round(clips, counts, set(), random.Random(0))
    assert len(out) == 10
    assert len({c["prompt_key"] for c in out}) == 10
    assert all(not c["clip_id"].endswith("a") for c in out)   # unanswered ones first


def test_pick_round_skips_seen_and_runs_out():
    clips = _clips(n_prompts=3)
    seen = {c["clip_id"] for c in clips[:8]}
    out = check.pick_round(clips, {}, seen, random.Random(0))
    assert [c["clip_id"] for c in out] == [clips[8]["clip_id"]]


def test_round_answer_and_no_repeat(client):
    r = client.get("/api/check/round", params={"rater": "r1"}).json()
    assert len(r["items"]) == 10 and r["left"] == 42 - 10
    first = r["items"][0]
    assert first["video_url"].endswith(".mp4") and "prompt_text" in first
    for it in r["items"]:
        ok = client.post("/api/check/answer", json={"clip_id": it["clip_id"], "verdict": "pass",
                                                    "elapsed_ms": 1000, "rater_id": "r1"})
        assert ok.status_code == 200
    # a retry of the same verdict is not a second answer
    client.post("/api/check/answer", json={"clip_id": first["clip_id"], "verdict": "fail",
                                           "elapsed_ms": 900, "rater_id": "r1"})
    r2 = client.get("/api/check/round", params={"rater": "r1"}).json()
    assert not {i["clip_id"] for i in r2["items"]} & {i["clip_id"] for i in r["items"]}
    db = dbmod.get_db()
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    n = loop.run_until_complete(db.check_answers.count_documents({"rater_id": "r1"}))
    assert n == 10
    doc = loop.run_until_complete(db.check_answers.find_one({"clip_id": first["clip_id"]}))
    assert doc["verdict"] == "fail"


def test_bad_verdict_and_unknown_clip(client):
    assert client.post("/api/check/answer", json={"clip_id": "c00a", "verdict": "maybe",
                                                  "elapsed_ms": 1}).status_code == 422
    assert client.post("/api/check/answer", json={"clip_id": "nope", "verdict": "pass",
                                                  "elapsed_ms": 1}).status_code == 400


def test_page_served_and_admin_gated(client):
    assert client.get("/check").status_code == 200
    assert client.get("/admin/check").status_code == 401
    assert client.get("/admin/check/export").status_code == 401
