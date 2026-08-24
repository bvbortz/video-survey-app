#!/usr/bin/env python
"""Flag a small, balanced set of pairs as `priority` so they collect several
independent judgements each.

WHY
    Verdicts spread evenly over 569 pairs per arm give roughly one judgement per
    pair, which supports no rater-level statistic: you cannot measure whether two
    people agree if no two people saw the same pair. Concentrating a few hundred
    new verdicts on ~50 pairs gives 3-4 judgements each, which is enough for an
    inter-rater agreement figure and a rater-clustered interval.

    This is a BIAS, not a filter. `PRIORITY_SHARE` in assignment.py favours these
    pairs; the rest of the pool stays reachable, and cross-round dedup is
    untouched, so a rater who returns still never sees a pair twice and simply
    falls through to the general pool once these are exhausted for them.

SELECTION
    Balanced across both forced-choice arms and across the three pre-registered
    subgroups, and spread over as many conditioning images as possible so the set
    is not an accident of one image. Within those constraints the least-judged
    pairs win, and ties are broken by a seeded shuffle so a re-run reproduces the
    same set rather than churning it.

USAGE
    This WRITES. It needs a read-write connection string, which must come from the
    environment -- never a command-line argument, which lands in shell history.

        export SURVEY_MONGO_WRITE_URI='mongodb+srv://<rw-user>:<pw>@...'
        python scripts/mark_priority_pairs.py --dry-run     # inspect first
        python scripts/mark_priority_pairs.py               # apply
        python scripts/mark_priority_pairs.py --clear       # undo, unflag all

    --dry-run prints exactly what would change and writes nothing.
"""
from __future__ import annotations

import argparse
import collections
import os
import random
import sys

import pymongo

VERSION = "inference5_20260822"
ARMS = ("short_vs_finetuned", "base_vs_finetuned")
SUBGROUPS = ("indirect", "misleading", "other")


def subgroup_of(pair: dict) -> str:
    if pair.get("origin") == "indirect":
        return "indirect"
    if str(pair.get("misleading")).strip().lower() == "true":
        return "misleading"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50, help="how many pairs to flag")
    ap.add_argument("--version", default=VERSION)
    ap.add_argument("--seed", type=int, default=1448)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--clear", action="store_true",
                    help="unflag every priority pair and exit")
    args = ap.parse_args()

    uri = os.environ.get("SURVEY_MONGO_WRITE_URI")
    if not uri:
        print("SURVEY_MONGO_WRITE_URI is not set (needs a read-WRITE user).",
              file=sys.stderr)
        return 2

    db = pymongo.MongoClient(uri).get_database("survey")

    if args.clear:
        n = db.pairs.count_documents({"priority": True})
        if args.dry_run:
            print(f"[dry-run] would unflag {n} pairs")
            return 0
        db.pairs.update_many({"priority": True}, {"$unset": {"priority": ""}})
        print(f"unflagged {n} pairs")
        return 0

    pairs = list(db.pairs.find(
        {"version": args.version, "arm": {"$in": list(ARMS)},
         "is_attention_check": {"$ne": True}}))
    if not pairs:
        print(f"no pairs found for version {args.version}", file=sys.stderr)
        return 1

    counts = collections.Counter(
        r["pair_id"] for r in db.responses.find({}, {"pair_id": 1}))

    rng = random.Random(args.seed)
    rng.shuffle(pairs)   # seeded: re-running picks the same set back

    # Round-robin over (arm, subgroup) buckets so the flagged set is balanced by
    # construction rather than by luck, and prefer a fresh image at each step so
    # one conditioning image cannot dominate.
    buckets: dict[tuple, list] = {}
    for p in pairs:
        buckets.setdefault((p["arm"], subgroup_of(p)), []).append(p)
    for k in buckets:
        buckets[k].sort(key=lambda p: counts.get(p["pair_id"], 0))

    order = [(a, g) for a in ARMS for g in SUBGROUPS]
    chosen: list[dict] = []
    used_images: collections.Counter = collections.Counter()
    cursor = {k: 0 for k in order}
    while len(chosen) < args.n and any(cursor[k] < len(buckets.get(k, ()))
                                       for k in order):
        for k in order:
            if len(chosen) >= args.n:
                break
            pool = buckets.get(k, [])
            # take the least-judged pair whose image is least represented so far
            best, best_i = None, None
            for i in range(cursor[k], len(pool)):
                p = pool[i]
                if best is None or used_images[p.get("image_file")] < used_images[best.get("image_file")]:
                    best, best_i = p, i
                if used_images[p.get("image_file")] == 0:
                    break
            if best is None:
                continue
            pool.pop(best_i)
            chosen.append(best)
            used_images[best.get("image_file")] += 1

    by = collections.Counter((p["arm"], subgroup_of(p)) for p in chosen)
    print(f"selected {len(chosen)} pairs over {len(used_images)} images")
    for k in order:
        print(f"   {k[0]:19s} {k[1]:11s} {by[k]}")
    already = sum(1 for p in chosen if counts.get(p["pair_id"], 0))
    print(f"   {already} of them already carry at least one verdict")

    if args.dry_run:
        print("\n[dry-run] nothing written. Sample:")
        for p in chosen[:5]:
            print(f"   {p['pair_id']}  {(p.get('prompt_text') or '')[:70]}")
        return 0

    ids = [p["pair_id"] for p in chosen]
    db.pairs.update_many({"priority": True}, {"$unset": {"priority": ""}})
    res = db.pairs.update_many({"pair_id": {"$in": ids}},
                               {"$set": {"priority": True}})
    print(f"flagged {res.modified_count} pairs as priority")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
