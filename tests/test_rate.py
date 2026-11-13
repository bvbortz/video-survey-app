"""Rate the Clips (app/rate.py) against an in-memory Mongo."""
import asyncio
import random

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import db as dbmod
from app import main
from app import rate


def _clips(n_prompts=12, per=3, rate_only=True):
    return [{"clip_id": f"c{p:02d}{k}", "prompt_key": f"p{p:02d}", "prompt_text": f"do {p}",
             "prompt_text_he": None, "prompt_text_ru": f"ru {p}" if p % 2 == 0 else None,
             "file": f"check/clips/c{p:02d}{k}.mp4", "image_file": f"check/images/i{p:02d}.jpg",
             **({"rate_only": True} if rate_only else {})}
            for p in range(n_prompts) for k in "abc"[:per]]


def _prompts(clips, core=("p00", "p01", "p02")):
    by = {}
    for c in clips:
        by.setdefault(c["prompt_key"], []).append(c["clip_id"])
    return [{"prompt_key": k, "clips": ids, "tier": 0 if k in core else 1} for k, ids in by.items()]


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture
def db():
    d = AsyncMongoMockClient()["survey"]
    dbmod.set_db(d)
    clips = _clips()
    _run(d.check_clips.insert_many(clips))
    _run(d.rate_prompts.insert_many(_prompts(clips)))
    return d


@pytest.fixture
def client(db):
    from starlette.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


def _answer(it, rater="r1", best=None, **kw):
    order = [c["clip_id"] for c in it["clips"]]
    return {"prompt_key": it["prompt_key"], "order": order, "verdicts": {c: "pass" for c in order},
            "best": best or order[0], "elapsed_ms": 1000, "rater_id": rater, **kw}


def test_pick_round_core_first_then_fewest_answers():
    ps = _prompts(_clips())
    out = rate.pick_round(ps, {}, set(), random.Random(0))
    assert len(out) == rate.N_ROUND
    assert {p["prompt_key"] for p in out if p["tier"] == 0} == {"p00", "p01", "p02"}
    counts = {p["prompt_key"]: 3 for p in ps if p["tier"] == 1 and p["prompt_key"] != "p05"}
    out = rate.pick_round(ps, counts, {"p00", "p01", "p02"}, random.Random(0))
    assert out[0]["prompt_key"] == "p05"   # the only tier-1 prompt without answers comes first
    assert not {"p00", "p01", "p02"} & {p["prompt_key"] for p in out}


def test_round_shows_all_clips_of_a_prompt_and_never_repeats(client):
    r = client.get("/api/rate/round", params={"rater": "r1"}).json()
    assert len(r["items"]) == 5 and r["left"] == 12 - 5
    it = r["items"][0]
    assert sorted(c["clip_id"] for c in it["clips"]) == [f"{it['prompt_key'].replace('p', 'c')}{k}" for k in "abc"]
    assert all(c["url"].endswith(f"{c['clip_id']}.mp4") for c in it["clips"])
    for x in r["items"]:
        assert client.post("/api/rate/answer", json=_answer(x)).status_code == 200
    again = client.get("/api/rate/round", params={"rater": "r1"}).json()
    assert not {x["prompt_key"] for x in r["items"]} & {x["prompt_key"] for x in again["items"]}


def test_answer_stored_and_deduped(client, db):
    it = client.get("/api/rate/round", params={"rater": "r1"}).json()["items"][0]
    assert client.post("/api/rate/answer", json=_answer(it, best="same")).status_code == 200
    a = _answer(it)
    a["verdicts"][a["order"][1]] = "fail"
    assert client.post("/api/rate/answer", json=a).status_code == 200
    docs = _run(db.rate_answers.find({}, {"_id": 0}).to_list(None))
    assert len(docs) == 1
    d = docs[0]
    assert d["best"] == a["order"][0] and d["verdicts"][a["order"][1]] == "fail" and d["order"] == a["order"]


def test_same_is_stored_as_no_best(client, db):
    it = client.get("/api/rate/round", params={"rater": "r2"}).json()["items"][0]
    client.post("/api/rate/answer", json=_answer(it, rater="r2", best="same"))
    assert _run(db.rate_answers.find_one({"rater_id": "r2"}))["best"] is None


@pytest.mark.parametrize("change", ["missing_verdict", "bad_verdict", "bad_best", "foreign_clip"])
def test_answer_rejects_incomplete_or_foreign(client, change):
    it = client.get("/api/rate/round", params={"rater": "r1"}).json()["items"][0]
    a = _answer(it)
    if change == "missing_verdict":
        a["verdicts"].pop(a["order"][0])
    elif change == "bad_verdict":
        a["verdicts"][a["order"][0]] = "maybe"
    elif change == "bad_best":
        a["best"] = "c99a"
    else:
        a["order"] = a["order"][:2] + ["c99a"]
    assert client.post("/api/rate/answer", json=a).status_code == 400


def test_russian_gets_only_prompts_with_russian_text(client):
    r = client.get("/api/rate/round", params={"rater": "r3", "lang": "ru"}).json()
    assert r["items"] and all(x["prompt_text_ru"] for x in r["items"])
    assert r["left"] == 6 - len(r["items"])


def test_rate_only_clips_stay_out_of_check(client, db):
    _run(db.check_clips.insert_many([{**c, "clip_id": "x" + c["clip_id"]} for c in _clips(2, rate_only=False)]))
    r = client.get("/api/check/round", params={"rater": "r1"}).json()
    assert r["items"] and all(x["clip_id"].startswith("x") for x in r["items"])
