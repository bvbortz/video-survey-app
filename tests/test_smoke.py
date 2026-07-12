"""End-to-end smoke test against an in-memory Mongo (mongomock-motor).

Covers: session assignment (A/B hidden + randomised), response resolves back to the
correct leg, de-dup on re-submit, admin cookie gate. No real Mongo / no network.
"""
import asyncio

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import db as dbmod
from app import main


def _pair(pid, arm, short_file, other_leg, other_file, attention=False):
    return {
        "pair_id": pid, "generator": "ltx2", "version": "v1", "prompt_id": pid[-4:],
        "arm": arm, "prompt_text": f"do thing {pid}", "image_file": "img.png",
        "is_attention_check": attention,
        "legs": [
            {"leg": "short", "clip_id": f"{pid}_short", "file": short_file, "auto_score": 0.4},
            {"leg": other_leg, "clip_id": f"{pid}_{other_leg}", "file": other_file, "auto_score": 0.6},
        ],
    }


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient

    db = AsyncMongoMockClient()["survey"]
    pairs = []
    for i in range(8):
        arm = "short_vs_finetuned" if i % 2 else "short_vs_base"
        other = "finetuned" if i % 2 else "base"
        pairs.append(_pair(f"p{i:02d}", arm, f"p{i:02d}_s.mp4", other, f"p{i:02d}_o.mp4"))
    pairs.append(_pair("attn0", "short_vs_base", "broken_s.mp4", "base", "broken_o.mp4", attention=True))
    asyncio.get_event_loop().run_until_complete(db.pairs.insert_many(pairs))

    dbmod.set_db(db)
    monkeypatch.setattr(main, "VIDEO_BASE_URL", "https://cdn.example/videos")
    monkeypatch.setattr(main, "ADMIN_SECRET", "s3cret")
    # no MONGO_URI -> lifespan skips real init, keeps our mock db
    with TestClient(main.app) as c:
        yield c, db


def test_session_and_response(client):
    c, db = client
    s = c.get("/api/session").json()
    assert s["rubric"] and s["items"]
    # leg identity must not leak to the client: items expose only opaque A/B slots
    # (token is an opaque per-pair hash, used for cross-round dedup)
    for it in s["items"]:
        assert set(it) == {"index", "token", "prompt_text",
                           "image_url", "video_a", "video_b"}
    it = s["items"][0]
    assert it["video_a"].startswith("https://cdn.example/videos/")

    scores = {k: 7 for k in s["rubric"]}
    r = c.post("/api/response", json={
        "session_id": s["session_id"], "index": it["index"],
        "video_a": scores, "video_b": {k: 3 for k in s["rubric"]},
        "elapsed_ms": 1234,
        "flag_issue": True, "note": "NSFW content in video B",
    })
    assert r.status_code == 200

    # response was resolved to real leg names, and A/B mapped per server order
    doc = asyncio.get_event_loop().run_until_complete(
        db.responses.find_one({"session_id": s["session_id"], "index": it["index"]})
    )
    assert set(doc["ratings"]) <= {"short", "base", "finetuned"}
    assert len(doc["ratings"]) == 2
    assert doc["flag_issue"] is True
    assert doc["note"] == "NSFW content in video B"


def test_seen_pair_excluded_next_round(client):
    c, _ = client
    # rate a pair, then a new session with its token must not show it again
    s1 = c.get("/api/session").json()
    tok = s1["items"][0]["token"]
    s2 = c.get(f"/api/session?seen={tok}").json()
    assert tok not in {it["token"] for it in s2["items"]}


def test_within_session_clip_dedup():
    from app.assignment import build_session_items, _clips

    db = AsyncMongoMockClient()["survey"]

    def pair(pid, arm, c1, c2):
        other = arm.split("_vs_")[1]
        return {"pair_id": pid, "generator": pid.split("_")[0], "arm": arm,
                "prompt_id": "P", "is_attention_check": False,
                "legs": [{"leg": "short", "clip_id": c1, "file": c1 + ".mp4"},
                         {"leg": other, "clip_id": c2, "file": c2 + ".mp4"}]}

    # same prompt: ltx2's two arms share ltx2_short; framepack has its own clips
    pairs = [
        pair("ltx2_a", "short_vs_base", "ltx2_short", "ltx2_base"),
        pair("ltx2_b", "short_vs_finetuned", "ltx2_short", "ltx2_ft"),
        pair("fp_a", "short_vs_base", "fp_short", "fp_base"),
    ]
    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.pairs.insert_many(pairs))
    items = loop.run_until_complete(build_session_items(db, n_real=3, n_attention=0))

    ids = {it["pair_id"] for it in items}
    # the two ltx2 arms share a clip -> never both in one session
    assert not ({"ltx2_a", "ltx2_b"} <= ids)
    # no clip appears twice in a session
    all_clips = [c for it in items for c in _clips(it["pair"])]
    assert len(all_clips) == len(set(all_clips))


def test_bad_score_rejected(client):
    c, _ = client
    s = c.get("/api/session").json()
    bad = {k: 11 for k in s["rubric"]}
    r = c.post("/api/response", json={
        "session_id": s["session_id"], "index": 0,
        "video_a": bad, "video_b": bad, "elapsed_ms": 1,
    })
    assert r.status_code == 422


def test_flagged_pair_may_be_partial(client):
    c, db = client
    s = c.get("/api/session").json()
    it = s["items"][0]
    # rater flagged the pair after touching only one slider on one video
    r = c.post("/api/response", json={
        "session_id": s["session_id"], "index": it["index"],
        "video_a": {"prompt_adherence": 2}, "video_b": {},
        "elapsed_ms": 5, "flag_issue": True, "note": "prompt impossible for this image",
    })
    assert r.status_code == 200
    doc = asyncio.get_event_loop().run_until_complete(
        db.responses.find_one({"session_id": s["session_id"], "index": it["index"]})
    )
    assert doc["flag_issue"] is True
    assert doc["note"] == "prompt impossible for this image"
    # only the touched slider was stored; missing keys mean "not rated"
    rated, unrated = sorted(doc["ratings"].values(), key=len, reverse=True)
    assert rated == {"prompt_adherence": 2}
    assert unrated == {}


def test_unflagged_partial_rejected(client):
    c, _ = client
    s = c.get("/api/session").json()
    r = c.post("/api/response", json={
        "session_id": s["session_id"], "index": 0,
        "video_a": {"prompt_adherence": 2}, "video_b": {},
        "elapsed_ms": 5, "flag_issue": False,
    })
    assert r.status_code == 422


def test_unflagged_missing_scene_fidelity_ok(client):
    # pre-2026-07-11 cached clients submit without the scene_fidelity slider
    c, _ = client
    s = c.get("/api/session").json()
    legacy = {k: 7 for k in s["rubric"] if k != "scene_fidelity"}
    r = c.post("/api/response", json={
        "session_id": s["session_id"], "index": 0,
        "video_a": legacy, "video_b": legacy, "elapsed_ms": 9,
    })
    assert r.status_code == 200


def test_admin_gate(client):
    c, _ = client
    assert c.get("/admin").status_code == 401
    c.cookies.set("admin_token", "s3cret")
    j = c.get("/admin").json()
    assert "coverage" in j and "responses_per_arm" in j
