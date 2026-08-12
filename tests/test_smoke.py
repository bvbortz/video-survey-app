"""End-to-end smoke test against an in-memory Mongo (mongomock-motor).

Covers: session assignment (A/B hidden + randomised), response resolves back to the
correct leg, de-dup on re-submit, admin cookie gate. No real Mongo / no network.
"""
import asyncio

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import db as dbmod
from app import main
from app.assignment import pair_token


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
    # Comfortably more than one session's worth (N_ITEMS_REAL), so the cross-round
    # exclusion is exercised rather than defeated by an exhausted pool.
    for i in range(24):
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
        # `mode` says which answer UI to render; it says nothing about which leg
        # landed on which side, so it does not weaken this guard.
        assert set(it) == {"index", "token", "prompt_text", "prompt_text_he",
                           "image_url", "video_a", "video_b", "mode"}
        assert it["mode"] in {"mos", "2afc"}
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


def test_pairs_without_mode_default_to_rating(client):
    """Every pair loaded before forced choice existed has no `mode` field. Absent
    must mean "mos" — if it ever defaulted the other way, raters would be shown a
    choice for pairs the analysis expects rubric scores from."""
    c, _ = client
    s = c.get("/api/session").json()
    assert {it["mode"] for it in s["items"]} == {"mos"}


def _choice_client(monkeypatch):
    """A session whose only real pairs are forced choice."""
    from starlette.testclient import TestClient
    db = AsyncMongoMockClient()["survey"]
    pairs = []
    for i in range(8):
        p = _pair(f"c{i:02d}", "base_vs_finetuned", f"c{i:02d}_b.mp4",
                  "finetuned", f"c{i:02d}_f.mp4")
        p["legs"][0]["leg"] = "base"          # base vs finetuned; short not involved
        p["legs"][0]["clip_id"] = f"c{i:02d}_base"
        p["mode"] = "2afc"
        pairs.append(p)
    pairs.append(_pair("attnC", "short_vs_base", "b_s.mp4", "base", "b_o.mp4", attention=True))
    asyncio.get_event_loop().run_until_complete(db.pairs.insert_many(pairs))
    dbmod.set_db(db)
    monkeypatch.setattr(main, "VIDEO_BASE_URL", "https://cdn.example/videos")
    monkeypatch.setattr(main, "ADMIN_SECRET", "s3cret")
    return TestClient(main.app), db


def test_forced_choice_stores_leg_not_letter(monkeypatch):
    c, db = _choice_client(monkeypatch)
    with c:
        s = c.get("/api/session").json()
        assert s["choice_question"]["prompt"]
        it = next(i for i in s["items"] if i["mode"] == "2afc")

        r = c.post("/api/response", json={
            "session_id": s["session_id"], "index": it["index"],
            "choice": "A", "elapsed_ms": 900,
        })
        assert r.status_code == 200

        doc = asyncio.get_event_loop().run_until_complete(
            db.responses.find_one({"session_id": s["session_id"], "index": it["index"]}))
        # The whole point: "A" is a display position and is meaningless once this
        # session's randomisation is gone, so the leg must be resolved on write.
        assert doc["choice_leg"] in {"base", "finetuned"}
        assert doc["shown_as"] == "A"
        assert doc["mode"] == "2afc"
        assert "ratings" not in doc

        # and it matches the server's own A/B order for this assignment
        sess = asyncio.get_event_loop().run_until_complete(
            db.sessions.find_one({"session_id": s["session_id"]}))
        order = next(a["order"] for a in sess["assignments"] if a["index"] == it["index"])
        assert doc["choice_leg"] == order[0]


def test_forced_choice_tie_and_shape_mismatches(monkeypatch):
    c, db = _choice_client(monkeypatch)
    with c:
        s = c.get("/api/session").json()
        items = [i for i in s["items"] if i["mode"] == "2afc"]

        # a tie is a real answer, not a missing one
        assert c.post("/api/response", json={
            "session_id": s["session_id"], "index": items[0]["index"],
            "choice": "tie", "elapsed_ms": 800}).status_code == 200
        doc = asyncio.get_event_loop().run_until_complete(
            db.responses.find_one({"index": items[0]["index"]}))
        assert doc["choice_leg"] == "tie"

        # sliders sent for a forced-choice pair: the client and server disagree
        # about what was shown, so this must not be stored as if it were a rating
        assert c.post("/api/response", json={
            "session_id": s["session_id"], "index": items[1]["index"],
            "video_a": {k: 7 for k in s["rubric"]},
            "video_b": {k: 3 for k in s["rubric"]},
            "elapsed_ms": 800}).status_code == 400

        # unknown choice value
        assert c.post("/api/response", json={
            "session_id": s["session_id"], "index": items[1]["index"],
            "choice": "maybe", "elapsed_ms": 800}).status_code == 422

        # a flagged forced-choice pair may be submitted with no choice at all
        assert c.post("/api/response", json={
            "session_id": s["session_id"], "index": items[1]["index"],
            "elapsed_ms": 800, "flag_issue": True,
            "note": "prompt impossible"}).status_code == 200


def _mixed_client(monkeypatch, n_choice_pairs=12):
    """Both pools populated, as production will be."""
    from starlette.testclient import TestClient
    db = AsyncMongoMockClient()["survey"]
    pairs = []
    for i in range(24):
        arm = "short_vs_finetuned" if i % 2 else "short_vs_base"
        other = "finetuned" if i % 2 else "base"
        pairs.append(_pair(f"m{i:02d}", arm, f"m{i:02d}_s.mp4", other, f"m{i:02d}_o.mp4"))
    for i in range(n_choice_pairs):
        p = _pair(f"x{i:02d}", "base_vs_finetuned", f"x{i:02d}_b.mp4",
                  "finetuned", f"x{i:02d}_f.mp4")
        p["legs"][0]["leg"] = "base"
        p["legs"][0]["clip_id"] = f"x{i:02d}_base"
        p["mode"] = "2afc"
        pairs.append(p)
    pairs.append(_pair("attnM", "short_vs_base", "b_s.mp4", "base", "b_o.mp4", attention=True))
    asyncio.get_event_loop().run_until_complete(db.pairs.insert_many(pairs))
    dbmod.set_db(db)
    monkeypatch.setattr(main, "VIDEO_BASE_URL", "https://cdn.example/videos")
    monkeypatch.setattr(main, "ADMIN_SECRET", "s3cret")
    return TestClient(main.app), db


def test_attention_checks_are_off(monkeypatch):
    """No attention-check pair has ever been exported, so the branch was dead in
    production. Kept explicit so a session's length is what the block sizes say."""
    from app import assignment
    assert assignment.N_ATTENTION == 0
    c, db = _mixed_client(monkeypatch)
    with c:
        s = c.get("/api/session").json()
        sess = asyncio.get_event_loop().run_until_complete(db.sessions.find_one({}))
        assert all(a["kind"] == "real" for a in sess["assignments"])
        assert len(s["items"]) == assignment.N_ITEMS_REAL


def test_session_is_two_contiguous_blocks(monkeypatch):
    """Forced-choice pairs all come first, ratings all after. A rater must change
    task exactly once, at the labelled boundary — not item by item."""
    from app import assignment
    c, _ = _mixed_client(monkeypatch)
    with c:
        for _ in range(5):                    # selection is random; check it holds
            s = c.get("/api/session").json()
            modes = [it["mode"] for it in s["items"]]
            assert modes == sorted(modes, key=lambda m: m != "2afc"), modes
            assert modes.count("2afc") == assignment.N_CHOICE
            assert len(s["items"]) == assignment.N_ITEMS_REAL + assignment.N_ATTENTION  # attention is 0
            # no video is shown twice, across the block boundary included
            urls = [u for it in s["items"] for u in (it["video_a"], it["video_b"])]
            assert len(urls) == len(set(urls))


def test_choice_block_shrinks_once_the_arm_has_enough(monkeypatch):
    from app import assignment
    c, db = _mixed_client(monkeypatch)
    monkeypatch.setattr(assignment, "CHOICE_TARGET", 3)
    with c:
        asyncio.get_event_loop().run_until_complete(db.responses.insert_many(
            [{"session_id": "old", "index": i, "mode": "2afc"} for i in range(4)]))
        s = c.get("/api/session").json()
        assert [it["mode"] for it in s["items"]].count("2afc") == assignment.N_CHOICE_SATED


def test_no_choice_pairs_loaded_behaves_as_before(client):
    """The old deployment shape: nothing is 2afc, so the session is all ratings."""
    from app import assignment
    c, _ = client
    s = c.get("/api/session").json()
    assert all(it["mode"] == "mos" for it in s["items"])
    assert len(s["items"]) == assignment.N_ITEMS_REAL + assignment.N_ATTENTION  # attention is 0


def test_choice_rejected_on_rating_pair(client):
    c, _ = client
    s = c.get("/api/session").json()
    it = s["items"][0]
    assert c.post("/api/response", json={
        "session_id": s["session_id"], "index": it["index"],
        "choice": "A", "elapsed_ms": 500}).status_code == 400


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


def test_retired_pairs_are_never_served(client):
    """A refresh retires the previous version rather than deleting it: retired pairs
    stay queryable for the admin join, but no session may contain one."""
    c, db = client
    loop = asyncio.get_event_loop()

    # retire everything currently loaded, then add one live pair of each kind
    loop.run_until_complete(db.pairs.update_many({}, {"$set": {"active": False}}))
    fresh = _pair("new00", "short_vs_finetuned", "new_s.mp4", "finetuned", "new_o.mp4")
    fresh_attn = _pair("newattn", "short_vs_base", "a_s.mp4", "base", "a_o.mp4", attention=True)
    for p in (fresh, fresh_attn):
        p["version"] = "v2"
        p["active"] = True
    loop.run_until_complete(db.pairs.insert_many([fresh, fresh_attn]))

    for _ in range(5):        # selection is randomised, so sample it
        s = c.get("/api/session").json()
        # Only the live real pair. The live attention pair is absent because
        # N_ATTENTION is 0, not because retirement excluded it — the assertion that
        # matters here is that no *retired* pair appears.
        assert {it["token"] for it in s["items"]} == {pair_token("new00")}

    # retired docs still exist and still carry the fields the admin $lookup needs
    old = loop.run_until_complete(db.pairs.find_one({"pair_id": "p00"}))
    assert old["active"] is False and old["arm"] and old["generator"]


def test_admin_pairs_gallery(client):
    """Gallery ranks by the human gap, falls back to auto, and stars are togglable."""
    c, db = client
    loop = asyncio.get_event_loop()

    # p00 legs are short(0.4) / base(0.6). Rate it so the base leg looks much better.
    loop.run_until_complete(db.responses.insert_many([
        {"session_id": "s1", "index": 0, "pair_id": "p00",
         "ratings": {"short": {"visual_quality": 2}, "base": {"visual_quality": 9}}},
        {"session_id": "s2", "index": 0, "pair_id": "p00",
         "ratings": {"short": {"visual_quality": 3}, "base": {"visual_quality": 8}}},
    ]))

    assert c.get("/admin/pairs").status_code == 401          # gated like the rest
    assert c.get("/admin/pairs.json").status_code == 401
    c.cookies.set("admin_token", "s3cret")

    j = c.get("/admin/pairs.json").json()
    top = j["rows"][0]
    assert top["pair_id"] == "p00"                            # rated pair sorts first
    assert round(top["human_gap"], 2) == 6.0                  # (9+8)/2 - (2+3)/2
    assert top["n_ratings"] == 2
    assert all(r["human_gap"] is None for r in j["rows"][1:])  # unrated fall to the back

    # star it, and check the starred-only filter picks it up
    assert c.post("/admin/pairs/p00/star").json()["starred"] is True
    only = c.get("/admin/pairs.json?starred=1").json()
    assert [r["pair_id"] for r in only["rows"]] == ["p00"]
    assert c.post("/admin/pairs/p00/star").json()["starred"] is False   # toggles off

    assert "<title>Pairs" in c.get("/admin/pairs").text


def test_admin_gate(client):
    c, _ = client
    assert c.get("/admin").status_code == 401
    c.cookies.set("admin_token", "s3cret")
    j = c.get("/admin").json()
    assert "coverage" in j and "responses_per_arm" in j
