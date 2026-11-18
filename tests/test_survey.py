"""The survey at / (app/survey.py) against an in-memory Mongo."""
import asyncio
import random

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import db as dbmod
from app import main, survey


def _manifest(study="s1", n_prompts=30, n_core=4):
    clips, pairs = [], []
    for p in range(n_prompts):
        a, b = f"{study}b{p:02d}", f"{study}e{p:02d}"
        for c in (a, b):
            clips.append({"clip_id": c, "prompt_key": f"p{p:02d}", "prompt_text": f"do {p}",
                          "prompt_text_he": "he", "prompt_text_ru": "ru", "file": f"study/clips/{c}.mp4",
                          "image_file": f"study/images/i{p:02d}.jpg"})
        pairs.append({"pair_id": f"{study}-p{p:02d}", "study": study, "a": a, "b": b, "prompt_key": f"p{p:02d}",
                      "legs": {a: "base", b: "ext"}, "core": p < n_core})
    return clips, pairs


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient

    db = AsyncMongoMockClient()["survey"]
    dbmod.set_db(db)
    clips, pairs = _manifest()
    _run(db.study_clips.insert_many(clips))
    _run(db.study_pairs.insert_many(pairs))
    monkeypatch.setattr(main, "ADMIN_SECRET", "s3cret")
    with TestClient(main.app) as c:
        c.db = db
        yield c


def _answer(c, it, choice="first", rater="r1", src=""):
    return c.post("/api/answer", json={"pair_id": it["pair_id"], "first": it["first"], "second": it["second"],
                                       "choice": choice, "elapsed_ms": 900, "rater_id": rater, "src": src})


def test_pick_round_core_then_fewest_answers():
    _, pairs = _manifest()
    out = survey.pick_round(pairs, {}, set(), random.Random(0))
    assert len(out) == survey.N_ROUND and len({p["prompt_key"] for p in out}) == survey.N_ROUND
    assert sum(p["core"] for p in out) == survey.N_CORE and out[0]["core"] and out[1]["core"]
    counts = {p["pair_id"]: 3 for p in pairs[4:20]}
    out = survey.pick_round(pairs, counts, set(), random.Random(0))
    assert all(counts.get(p["pair_id"], 0) == 0 for p in out if not p["core"])


def test_pick_round_core_exhausted_and_fill():
    _, pairs = _manifest(n_prompts=10, n_core=4)
    core = {p["pair_id"] for p in pairs if p["core"]}
    out = survey.pick_round(pairs, {}, core, random.Random(0))
    assert len(out) == 6 and not any(p["core"] for p in out)   # only 6 others exist
    others = {p["pair_id"] for p in pairs if not p["core"]}
    out = survey.pick_round(pairs, {}, others, random.Random(0))
    assert len(out) == 4 and all(p["core"] for p in out)        # the rest of the core fills the round


def test_root_serves_the_study_page(client):
    r = client.get("/")
    assert r.status_code == 200 and 'data-api="/api"' in r.text and "/compare.js" in r.text


def test_round_hides_legs_and_answer_stores_study_and_leg(client):
    r = client.get("/api/round", params={"rater": "r1"}).json()
    assert len(r["items"]) == 8 and r["left"] == 30 - 8
    for it in r["items"]:
        assert "legs" not in it and "core" not in it and "study" not in it
    it = r["items"][0]
    assert _answer(client, it, src="fam").status_code == 200
    doc = _run(client.db.study_answers.find_one({"rater_id": "r1"}))
    assert doc["study"] == "s1" and doc["better"] == it["first"] and doc["src"] == "fam"
    assert doc["better_leg"] == ("base" if it["first"].startswith("s1b") else "ext")
    assert _answer(client, it, choice="same").status_code == 200
    docs = _run(client.db.study_answers.find({"rater_id": "r1"}).to_list(10))
    assert len(docs) == 1 and docs[0]["better_leg"] is None   # de-duped, the later answer stands
    r2 = client.get("/api/round", params={"rater": "r1"}).json()
    assert it["pair_id"] not in {x["pair_id"] for x in r2["items"]}


def test_retired_study_is_not_served(client):
    """a new study replaces the old at /: only active pairs are served, old answers keep their tag"""
    it = client.get("/api/round", params={"rater": "r1"}).json()["items"][0]
    _answer(client, it)
    _run(client.db.study_pairs.update_many({}, {"$set": {"active": False}}))
    clips, pairs = _manifest(study="s2", n_prompts=12)
    _run(client.db.study_clips.insert_many(clips))
    _run(client.db.study_pairs.insert_many(pairs))
    r = client.get("/api/round", params={"rater": "r1"}).json()
    assert r["items"] and all(x["pair_id"].startswith("s2-") for x in r["items"])
    _answer(client, r["items"][0])
    studies = sorted(d["study"] for d in _run(client.db.study_answers.find({}).to_list(10)))
    assert studies == ["s1", "s2"]


def test_answer_stores_verdicts_by_leg(client):
    it = client.get("/api/round", params={"rater": "r9"}).json()["items"][0]
    body = {"pair_id": it["pair_id"], "first": it["first"], "second": it["second"], "choice": "same",
            "elapsed_ms": 5, "rater_id": "r9", "verdict_first": "pass", "verdict_second": "fail"}
    assert client.post("/api/answer", json=body).status_code == 200
    doc = _run(client.db.study_answers.find_one({"rater_id": "r9"}))
    first_leg = "base" if it["first"].startswith("s1b") else "ext"
    second_leg = {"base": "ext", "ext": "base"}[first_leg]
    assert doc["verdicts"] == {it["first"]: "pass", it["second"]: "fail"}
    assert doc["verdict_leg"] == {first_leg: "pass", second_leg: "fail"}
    assert client.post("/api/answer", json={**body, "verdict_first": "great"}).status_code == 422


def test_answer_rejects_foreign_clip(client):
    bad = client.post("/api/answer", json={"pair_id": "s1-p00", "first": "s1b00", "second": "s1e01",
                                           "choice": "first", "elapsed_ms": 1})
    assert bad.status_code == 400


def test_admin_gate_and_export_by_study(client):
    assert client.get("/admin").status_code == 401
    it = client.get("/api/round", params={"rater": "r1"}).json()["items"][0]
    _answer(client, it)
    client.cookies.set("admin_token", "s3cret")
    a = client.get("/admin").json()
    assert a["live"] == ["s1"] and a["studies"]["s1"]["answers"] == 1
    assert len(client.get("/admin/export", params={"study": "s1"}).json()) == 1
    assert client.get("/admin/export", params={"study": "other"}).json() == []
