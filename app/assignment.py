"""Per-session pair selection.

Goal: balanced coverage without ever showing a rater the same *video* twice.

- Hand out the least-judged pairs first, keep the two arms roughly even.
- Randomise which leg lands on side A vs B — the manifest stores canonical order
  only; the *server* decides display order so the rater can't guess the leg.
- Dedup is at the CLIP level, not the prompt level. A prompt has up to 6 clips
  (M1/M2 × short/base/finetuned); the same prompt may appear more than once as long
  as the clips differ. Two pairs that share a clip (e.g. a generator's two arms both
  contain that generator's "short" clip) are never both shown to one rater — within a
  session or across rounds.
- Cross-round memory is by an OPAQUE per-pair token (see pair_token). Clip ids encode
  the leg name, so they must never reach the client; a token reveals nothing.

A session = N_REAL scored pairs + N_ATTENTION obvious-failure pairs (quality gate).
"""
from __future__ import annotations

import hashlib
import random

N_REAL = 6
N_ATTENTION = 1


def pair_token(pair_id: str) -> str:
    """Opaque, stable id the client can store for cross-round dedup (no leg leak)."""
    return hashlib.sha1(pair_id.encode()).hexdigest()[:12]


def _clips(pair: dict) -> set:
    return {leg["clip_id"] for leg in pair["legs"]}


async def _judged_counts(db) -> dict[str, int]:
    counts: dict[str, int] = {}
    cur = db.responses.aggregate([{"$group": {"_id": "$pair_id", "n": {"$sum": 1}}}])
    async for row in cur:
        counts[row["_id"]] = row["n"]
    return counts


def _round_robin(pool: list[dict], n: int, chosen: list[dict], used_clips: set) -> None:
    """Round-robin across arms (each least-judged first), skipping any pair that
    shares a clip with one already chosen (or already seen, if preloaded)."""
    by_arm: dict[str, list[dict]] = {}
    for p in pool:
        by_arm.setdefault(p["arm"], []).append(p)
    for a in by_arm:
        by_arm[a].sort(key=lambda p: (p["_n"], random.random()))
    arms = list(by_arm)
    random.shuffle(arms)
    idx = {a: 0 for a in arms}
    while len(chosen) < n and any(idx[a] < len(by_arm[a]) for a in arms):
        for a in arms:
            if len(chosen) >= n:
                break
            while idx[a] < len(by_arm[a]) and (_clips(by_arm[a][idx[a]]) & used_clips):
                idx[a] += 1
            if idx[a] < len(by_arm[a]):
                p = by_arm[a][idx[a]]
                idx[a] += 1
                chosen.append(p)
                used_clips |= _clips(p)


def _select(reals: list[dict], n: int, seen_clips: set) -> list[dict]:
    """Pick n pairs. First pass excludes clips the rater has already seen; if that
    can't fill the session (a rater who's done many rounds), a second pass relaxes
    the cross-round exclusion but still never repeats a clip within this session."""
    chosen: list[dict] = []
    _round_robin(reals, n, chosen, set(seen_clips))
    if len(chosen) < n:
        within = set().union(*(_clips(p) for p in chosen)) if chosen else set()
        _round_robin(reals, n, chosen, within)
    return chosen[:n]


def _make_item(pair: dict, kind: str) -> dict:
    """Attach a randomised A/B leg order to a pair."""
    order = [leg["leg"] for leg in pair["legs"]]
    random.shuffle(order)
    return {"pair_id": pair["pair_id"], "kind": kind, "order": order, "pair": pair}


async def build_session_items(
    db, seen_tokens: set | None = None,
    n_real: int = N_REAL, n_attention: int = N_ATTENTION,
) -> list[dict]:
    seen_tokens = set(seen_tokens or ())
    counts = await _judged_counts(db)

    reals = [p async for p in db.pairs.find({"is_attention_check": {"$ne": True}})]
    for p in reals:
        p["_n"] = counts.get(p["pair_id"], 0)

    # cross-round: clips the rater already saw, derived from their seen pair tokens
    seen_clips: set = set()
    if seen_tokens:
        for p in reals:
            if pair_token(p["pair_id"]) in seen_tokens:
                seen_clips |= _clips(p)

    chosen = _select(reals, n_real, seen_clips)

    attn = [p async for p in db.pairs.find({"is_attention_check": True})]
    random.shuffle(attn)
    attn = attn[:n_attention]

    real_items = [_make_item(p, "real") for p in chosen]
    attn_items = [_make_item(p, "attention") for p in attn]

    random.shuffle(real_items)
    seq = list(real_items)
    for a in attn_items:                      # drop attention check(s) mid-session
        seq.insert(max(1, len(seq) // 2), a)
    return seq
