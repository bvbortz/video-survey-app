"""Per-session pair selection.

Goal: balanced coverage. Hand out the least-judged pairs first, keep the two arms
roughly even, randomise which leg lands on side A vs B (the manifest stores canonical
order only — the *server* decides display order so the rater can't guess the leg).

A session = N_REAL scored pairs + N_ATTENTION obvious-failure pairs (quality gate)
+ N_REPEAT repeat of a real pair (intra-rater consistency). The leg identity is never
sent to the client; only the resolved video URLs for side A / side B are.
"""
from __future__ import annotations

import random

N_REAL = 6
N_ATTENTION = 1
N_REPEAT = 1


async def _judged_counts(db) -> dict[str, int]:
    counts: dict[str, int] = {}
    cur = db.responses.aggregate([{"$group": {"_id": "$pair_id", "n": {"$sum": 1}}}])
    async for row in cur:
        counts[row["_id"]] = row["n"]
    return counts


def _balanced_take(reals: list[dict], n: int) -> list[dict]:
    """Round-robin across arms, each arm ordered least-judged first."""
    by_arm: dict[str, list[dict]] = {}
    for p in reals:
        by_arm.setdefault(p["arm"], []).append(p)
    for a in by_arm:
        by_arm[a].sort(key=lambda p: (p["_n"], random.random()))
    arms = list(by_arm)
    random.shuffle(arms)
    idx = {a: 0 for a in arms}
    chosen: list[dict] = []
    while len(chosen) < n and any(idx[a] < len(by_arm[a]) for a in arms):
        for a in arms:
            if len(chosen) >= n:
                break
            if idx[a] < len(by_arm[a]):
                chosen.append(by_arm[a][idx[a]])
                idx[a] += 1
    return chosen[:n]


def _make_item(pair: dict, kind: str) -> dict:
    """Attach a randomised A/B leg order to a pair."""
    order = [leg["leg"] for leg in pair["legs"]]
    random.shuffle(order)
    return {"pair_id": pair["pair_id"], "kind": kind, "order": order, "pair": pair}


async def build_session_items(
    db, n_real: int = N_REAL, n_attention: int = N_ATTENTION, n_repeat: int = N_REPEAT
) -> list[dict]:
    counts = await _judged_counts(db)

    reals = [p async for p in db.pairs.find({"is_attention_check": {"$ne": True}})]
    for p in reals:
        p["_n"] = counts.get(p["pair_id"], 0)
    chosen = _balanced_take(reals, n_real)

    attn = [p async for p in db.pairs.find({"is_attention_check": True})]
    random.shuffle(attn)
    attn = attn[:n_attention]

    repeats = [dict(random.choice(chosen))] if (chosen and n_repeat) else []

    real_items = [_make_item(p, "real") for p in chosen]
    attn_items = [_make_item(p, "attention") for p in attn]
    rep_items = [_make_item(p, "repeat") for p in repeats]

    random.shuffle(real_items)
    seq = list(real_items)
    for a in attn_items:                      # drop attention check(s) mid-session
        seq.insert(max(1, len(seq) // 2), a)
    seq.extend(rep_items)                      # repeated pair last
    return seq
