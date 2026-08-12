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

# A session runs in two blocks: the forced-choice pairs first, then the rating pairs.
# Raters do not switch task format item by item — mode-switching mid-session is a
# known source of inconsistency, and the two formats ask for very different effort
# (one decision vs ten slider drags).
N_ITEMS_REAL = 9      # real pairs per session, split between the two blocks

# Off. export_survey_pairs.py has always written is_attention_check: False for every
# pair, so no attention-check pair has ever existed in the manifest and this branch
# has been dead in production — sessions were 6 real pairs, not 7. The selection code
# below still honours a non-zero value, so a designated obvious-failure pair can be
# reintroduced by exporting one and raising this; nothing else needs to change.
N_ATTENTION = 0

# `base_vs_finetuned` is the comparison the paper's claim rests on and the only one
# never asked directly, so it gets the larger block until it can actually answer:
# ~542 non-tie responses for a 56/44 split, ~194 for 60/40. Past the target it drops
# to a maintenance share and the rating arms get the slots back — the X-vs-short data
# is what the evaluator-agreement analysis is built on, so it must not starve either.
N_CHOICE = 5
N_CHOICE_SATED = 2
CHOICE_TARGET = 542

# Retired pairs stay in the collection so old responses can still be joined back to
# their arm/generator (the admin stats do exactly that), but they are never handed
# out again. Absent field == active, so pairs loaded before this existed still serve.
ACTIVE = {"active": {"$ne": False}}


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


def _select(reals: list[dict], n: int, seen_clips: set,
            used_clips: set | None = None) -> list[dict]:
    """Pick n pairs. First pass excludes clips the rater has already seen; if that
    can't fill the session (a rater who's done many rounds), a second pass relaxes
    the cross-round exclusion but still never repeats a clip within this session.

    `used_clips`, when given, is shared across the two blocks and mutated, so a clip
    taken by the forced-choice block cannot reappear in the rating block. That matters
    here specifically: base_vs_finetuned shares its base clip with short_vs_base and
    its finetuned clip with short_vs_finetuned, so without it a rater would see the
    same video twice in one session.
    """
    chosen: list[dict] = []
    blocked = set(seen_clips) | set(used_clips or ())
    _round_robin(reals, n, chosen, blocked)
    if len(chosen) < n:
        within = set(used_clips or ())
        within |= set().union(*(_clips(p) for p in chosen)) if chosen else set()
        _round_robin(reals, n, chosen, within)
    chosen = chosen[:n]
    if used_clips is not None:
        for p in chosen:
            used_clips |= _clips(p)
    return chosen


def _make_item(pair: dict, kind: str) -> dict:
    """Attach a randomised A/B leg order to a pair."""
    order = [leg["leg"] for leg in pair["legs"]]
    random.shuffle(order)
    return {"pair_id": pair["pair_id"], "kind": kind, "order": order, "pair": pair}


async def _choice_block_size(db) -> int:
    """How many forced-choice slots this session gets.

    Counts responses already collected for the forced-choice arm; once that arm can
    answer its own question the block shrinks and the rating arms get the slots back.
    """
    try:
        have = await db.responses.count_documents({"mode": "2afc"})
    except Exception:            # a counting failure must never deny someone a session
        return N_CHOICE
    return N_CHOICE if have < CHOICE_TARGET else N_CHOICE_SATED


async def build_session_items(
    db, seen_tokens: set | None = None,
    n_real: int = N_ITEMS_REAL, n_attention: int = N_ATTENTION,
) -> list[dict]:
    seen_tokens = set(seen_tokens or ())
    counts = await _judged_counts(db)

    reals = [p async for p in db.pairs.find({"is_attention_check": {"$ne": True}, **ACTIVE})]
    for p in reals:
        p["_n"] = counts.get(p["pair_id"], 0)

    # cross-round: clips the rater already saw, derived from their seen pair tokens
    seen_clips: set = set()
    if seen_tokens:
        for p in reals:
            if pair_token(p["pair_id"]) in seen_tokens:
                seen_clips |= _clips(p)

    # Absent mode == rating, matching the manifest and the app. A deployment with no
    # forced-choice pairs loaded therefore behaves exactly as it did before.
    choice_pool = [p for p in reals if p.get("mode") == "2afc"]
    rating_pool = [p for p in reals if p.get("mode") != "2afc"]

    n_choice = min(await _choice_block_size(db), n_real) if choice_pool else 0
    used_clips: set = set()
    chosen_choice = _select(choice_pool, n_choice, seen_clips, used_clips)
    # Whatever the choice block could not fill goes to ratings, so the session is
    # still full when one pool runs out for this particular rater.
    chosen_rating = _select(rating_pool, n_real - len(chosen_choice),
                            seen_clips, used_clips)

    attn = [p async for p in db.pairs.find({"is_attention_check": True, **ACTIVE})]
    random.shuffle(attn)
    attn = attn[:n_attention]

    choice_items = [_make_item(p, "real") for p in chosen_choice]
    rating_items = [_make_item(p, "real") for p in chosen_rating]

    # Shuffle WITHIN each block, never across: the blocks stay contiguous so the rater
    # changes task exactly once, at a boundary the page labels.
    random.shuffle(choice_items)
    random.shuffle(rating_items)
    for a in attn:              # the attention check is a rating pair, so it goes there
        rating_items.insert(max(1, len(rating_items) // 2), _make_item(a, "attention"))
    return choice_items + rating_items
