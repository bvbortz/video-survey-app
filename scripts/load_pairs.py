#!/usr/bin/env python3
"""Load pairs.json (from export_survey_pairs.py) into MongoDB.

Idempotent: upserts by pair_id / clip_id, so re-running after a new export (e.g.
FramePack legs added, or a retrain) just adds/updates rows.

Usage:
  export MONGO_URI='mongodb+srv://survey_app:...@.../survey'
  python scripts/load_pairs.py ../user-survey/pairs.json
  python scripts/load_pairs.py pairs.json --drop   # wipe collections first
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from pymongo import MongoClient, UpdateOne


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", help="path to pairs.json")
    ap.add_argument("--db", default="survey")
    ap.add_argument("--drop", action="store_true", help="drop pairs/clips first")
    ap.add_argument("--retire-others", action="store_true",
                    help="set active=False on every pair whose version is NOT in this "
                         "manifest, so raters are served only the new set. Retired pairs "
                         "stay in the collection because the admin per-arm stats join old "
                         "responses back to them. Undo with --unretire.")
    ap.add_argument("--unretire", action="store_true",
                    help="clear active=False everywhere (undoes --retire-others)")
    args = ap.parse_args()

    uri = os.environ.get("MONGO_URI")
    if not uri:
        print("set MONGO_URI", file=sys.stderr)
        return 2

    with open(args.manifest) as f:
        manifest = json.load(f)
    pairs = manifest["pairs"]
    clips = manifest.get("clips", [])

    db = MongoClient(uri)[args.db]
    if args.drop:
        db.pairs.drop()
        db.clips.drop()

    db.pairs.create_index("pair_id", unique=True)
    db.clips.create_index("clip_id", unique=True)

    if pairs:
        db.pairs.bulk_write(
            [UpdateOne({"pair_id": p["pair_id"]}, {"$set": p}, upsert=True) for p in pairs]
        )
    if clips:
        db.clips.bulk_write(
            [UpdateOne({"clip_id": c["clip_id"]}, {"$set": c}, upsert=True) for c in clips]
        )

    # Carry Hebrew onto pairs that did not exist when it was pushed.
    #
    # The manifest has no prompt_text_he — translations live only here, written by
    # push_hebrew_prompts.py and keyed on the English prompt_text. $set leaves the
    # field alone on an existing pair, but a NEWLY inserted pair has never had it, so
    # a new arm silently serves English to Hebrew raters. That is what happened to the
    # 366 base_vs_finetuned pairs: every one of their prompts was already translated,
    # just not on those documents.
    #
    # Copying from a sibling with the same English text needs no translation file and
    # no re-run, and it cannot invent a translation that does not already exist.
    untranslated = list(db.pairs.find(
        {"$or": [{"prompt_text_he": {"$exists": False}}, {"prompt_text_he": None}]},
        {"pair_id": 1, "prompt_text": 1}))
    if untranslated:
        known = {}
        for d in db.pairs.find(
                {"prompt_text_he": {"$exists": True, "$ne": None}},
                {"prompt_text": 1, "prompt_text_he": 1}):
            known.setdefault(d["prompt_text"], d["prompt_text_he"])
        ops = [UpdateOne({"pair_id": d["pair_id"]},
                         {"$set": {"prompt_text_he": known[d["prompt_text"]]}})
               for d in untranslated if d.get("prompt_text") in known]
        if ops:
            db.pairs.bulk_write(ops)
        print(f"  Hebrew backfilled onto {len(ops)} pairs")
        still = len(untranslated) - len(ops)
        if still:
            print(f"  ! {still} pairs have no Hebrew anywhere — run "
                  "scripts/push_hebrew_prompts.py with an updated i18n_prompts_he.json")

    # Retire by VERSION, not by pair_id: a version is one export of one generator, which
    # is exactly the unit being replaced. Doing it after the upsert means the pairs just
    # loaded are already active and can never retire themselves.
    versions = sorted({p["version"] for p in pairs})
    if args.retire_others:
        res = db.pairs.update_many({"version": {"$nin": versions}}, {"$set": {"active": False}})
        db.pairs.update_many({"version": {"$in": versions}}, {"$set": {"active": True}})
        print(f"  retired {res.modified_count} pairs outside version(s) {versions}")
    elif args.unretire:
        res = db.pairs.update_many({"active": False}, {"$set": {"active": True}})
        print(f"  un-retired {res.modified_count} pairs")

    print(f"loaded {len(pairs)} pairs, {len(clips)} clips into '{args.db}'")
    print("  attention-check pairs:",
          db.pairs.count_documents({"is_attention_check": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
