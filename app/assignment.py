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

# Two arms are now served as forced choice: `base_vs_finetuned` (the comparison the
# paper's claim rests on, never asked directly before) and `short_vs_finetuned`
# (added 2026-08-22 — the paper's headline human number had no independent
# corroboration because that arm was MOS-only, and MOS became opt-in). They are
# weighted EQUALLY; see _round_robin, which alternates arms within every quota slot.
#
# The target is per arm: ~542 non-tie responses for a 56/44 split, ~194 for 60/40.
# With two arms sharing the block, the count below has to clear twice that before
# the block shrinks, or the first arm to arrive would sate the second one's budget.
# Past the target it drops to a maintenance share and the rating arms get the slots
# back — short_vs_base and short_vs_enhance still feed the evaluator-agreement
# analysis, so they must not starve either.
#
# Note this only governs the legacy `block=None` session. The app now opens in
# block="choice", which takes every real slot regardless.
N_CHOICE = 5
N_CHOICE_SATED = 2
CHOICE_TARGET = 542 * 2

# --- pre-registered subgroups -------------------------------------------------
# The open claim is that the finetune's advantage over base concentrates on
# prompts that are oblique (`origin == "indirect"`) or that carry one deliberately
# wrong detail (`misleading == True`). They are DISJOINT populations from
# different generators — 97 and 61 prompts of 569 — and are reported separately,
# so each needs ~49 decisive verdicts (Holm, two subgroups).
#
# Left to itself the round-robin would sample them in proportion to the pool and
# spend ~72% of every session on prompts that answer neither question. So the
# choice block runs a QUOTA instead: equal thirds.
#
# Equal rather than subgroup-heavy because the claim is a COMPARISON — the
# advantage is supposed to be larger on these prompts than on ordinary ones. That
# contrast needs `other` from the same rater population at comparable precision;
# borrowing the existing 562 in-house verdicts would mix rater populations. A
# subgroup-heavy split reaches "indirect beats 50%" sooner but leaves "indirect
# beats other" underpowered longest, and the second is the actual claim.
#
# This is an OVERSAMPLE, not a filter: all 569 prompts stay reachable, every
# response records which stratum it came from, and the pooled estimate is
# recovered by weighting strata back to their pool shares. An analysis that
# ignores `subgroup` and averages raw responses will be biased — that is the
# price of the quota and the reason the field is stored.
def subgroup_of(pair: dict) -> str:
    if pair.get("origin") == "indirect":
        return "indirect"
    if pair.get("misleading"):
        return "misleading"
    return "other"


SUBGROUP_QUOTA = {"indirect": 1, "misleading": 1, "other": 1}   # balanced three ways

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
    shares a clip with one already chosen (or already seen, if preloaded).

    This is what makes the two forced-choice arms equally weighted: the alternation
    is per arm, and the starting arm is shuffled per call, so a 3-slot quota group
    splits 2/1 one way or the other and evens out across sessions rather than
    always favouring whichever arm sorts first.

    The clip-sharing skip matters more now that both arms exist.
    `base_vs_finetuned` and `short_vs_finetuned` share the *finetuned* clip for a
    given prompt, so without it a rater could be asked about the same finetuned
    video twice and the two verdicts would be correlated. `used_clips` blocks that
    inside a session and `seen_clips` blocks it across rounds.
    """
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
            used_clips: set | None = None, strict: bool = False) -> list[dict]:
    """Pick n pairs, excluding clips the rater has already seen.

    With `strict` (what the choice block uses) that exclusion is absolute: a
    stratum that cannot fill its slots from unseen pairs yields them rather than
    repeating, the caller cascades the shortfall to the other strata, and an
    exhausted pool returns a short session. Without it, a second pass relaxes the
    cross-round exclusion to keep a session full — the original behaviour, still
    used by the rating block.

    `used_clips`, when given, is shared across the two blocks and mutated, so a clip
    taken by the forced-choice block cannot reappear in the rating block. That matters
    here specifically: base_vs_finetuned shares its base clip with short_vs_base and
    its finetuned clip with short_vs_finetuned, so without it a rater would see the
    same video twice in one session.
    """
    chosen: list[dict] = []
    blocked = set(seen_clips) | set(used_clips or ())
    _round_robin(reals, n, chosen, blocked)
    # strict: a rater must never be shown a clip twice, so a stratum that cannot
    # fill its slots from unseen pairs simply yields them. _select_quota then
    # cascades the shortfall to the other strata, and if the whole pool is
    # exhausted for this rater the session comes back short rather than
    # repeating. Re-showing a pair would silently correlate two "independent"
    # verdicts from the same person on the same clips.
    if len(chosen) < n and not strict:
        within = set(used_clips or ())
        within |= set().union(*(_clips(p) for p in chosen)) if chosen else set()
        _round_robin(reals, n, chosen, within)
    chosen = chosen[:n]
    if used_clips is not None:
        for p in chosen:
            used_clips |= _clips(p)
    return chosen


def _allocate(n: int) -> dict[str, int]:
    """Split n slots across the strata in SUBGROUP_QUOTA's ratio, exactly.

    Largest-remainder, not per-stratum rounding. Rounding each share
    independently does not sum to n, and the error does not land evenly: with
    n=9 and a 2/2/1 quota, round() asks for 4+4+2=10 slots, the two big strata
    are served first, and `other` silently collapses from the declared 20% to
    11%. `other` is the comparison group the subgroup claim is measured
    against, so starving it quietly weakens the very contrast being collected.

    Returns strata in descending quota order: the scarce, heavily-oversampled
    strata pick before `other` consumes a clip they might have shared.
    """
    total = max(1, sum(SUBGROUP_QUOTA.values()))
    exact = {g: n * q / total for g, q in SUBGROUP_QUOTA.items()}
    out = {g: int(v) for g, v in exact.items()}
    # Hand out the leftover slots to the largest fractional parts.
    left = n - sum(out.values())
    for g in sorted(exact, key=lambda k: (-(exact[k] - out[k]), -SUBGROUP_QUOTA[k])):
        if left <= 0:
            break
        out[g] += 1
        left -= 1
    return {g: out[g] for g in sorted(out, key=lambda k: -SUBGROUP_QUOTA[k])}


def _select_quota(pool: list[dict], n: int, seen_clips: set,
                  used_clips: set) -> list[dict]:
    """Fill n choice slots by subgroup quota, least-judged first within each.

    Quota shortfalls cascade: `misleading` is the smallest pool (61 prompts) and
    a rater who has already seen most of it cannot be served two more, so the
    slots it cannot fill go to the other strata rather than shortening the
    session. Under-filling would quietly punish exactly the raters who have given
    the most.
    """
    chosen: list[dict] = []
    by_group: dict[str, list[dict]] = {}
    for p in pool:
        by_group.setdefault(subgroup_of(p), []).append(p)

    for group, want in _allocate(n).items():
        if want <= 0:
            continue
        _select_into(by_group.get(group, []), want, seen_clips, used_clips, chosen)

    # Cascade: whatever the quota could not fill, take from anything left.
    if len(chosen) < n:
        taken = {p["pair_id"] for p in chosen}
        _select_into([p for p in pool if p["pair_id"] not in taken],
                     n - len(chosen), seen_clips, used_clips, chosen)
    return chosen[:n]


def _select_into(pool: list[dict], n: int, seen_clips: set, used_clips: set,
                 chosen: list[dict]) -> None:
    """_select() semantics, appending into an existing `chosen` list."""
    chosen.extend(_select(pool, n, seen_clips, used_clips, strict=True))


def _make_item(pair: dict, kind: str) -> dict:
    """Attach a randomised A/B leg order to a pair."""
    order = [leg["leg"] for leg in pair["legs"]]
    random.shuffle(order)
    return {"pair_id": pair["pair_id"], "kind": kind, "order": order, "pair": pair,
            # Stored on the assignment and copied onto the response, so the
            # stratum a verdict came from survives even if the pair document is
            # later edited or the quota is retuned mid-collection.
            "subgroup": subgroup_of(pair)}


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
    block: str | None = None,
) -> list[dict]:
    """Build one session's items.

    `block` selects the shape:
      None      — the default session: forced-choice block, then rating block.
      "choice"  — forced choice only. This is the endless continuation a rater
                  gets after finishing a set, and the default the app now opens
                  with: a comparison costs ~36s against ~70s for a rating pair,
                  and the AB arm is the one starved of data (75 responses against
                  437 ratings), so the marginal minute of a volunteer's attention
                  is worth roughly twice as much spent here.
      "rating"  — rating only, for the rater who opts into it explicitly.
    """
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

    if block == "choice":
        n_choice, n_rating = n_real, 0
    elif block == "rating":
        n_choice, n_rating = 0, n_real
    else:
        n_choice = min(await _choice_block_size(db), n_real) if choice_pool else 0
        n_rating = n_real - n_choice

    used_clips: set = set()
    chosen_choice = _select_quota(choice_pool, n_choice, seen_clips, used_clips) \
        if n_choice else []
    # Whatever the choice block could not fill goes to ratings, so the session is
    # still full when one pool runs out for this particular rater. Not in
    # block="choice": there the rater asked for comparisons, and quietly handing
    # them a ten-slider rating form instead is how you lose them for good.
    if block != "choice":
        n_rating = n_real - len(chosen_choice)
    chosen_rating = _select(rating_pool, n_rating, seen_clips, used_clips) \
        if n_rating else []

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
