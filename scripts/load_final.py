#!/usr/bin/env python3
"""Load the final survey's manifest (finetune-data-gen/final_survey.py export ->
user-survey/final_manifest.json) into MongoDB for app/final.py: final_clips and final_pairs.

Idempotent: upserts by clip_id / pair_id. --retire-others sets active=False on pairs not in
this manifest (their answers stay joinable). Refuses a manifest whose pairs name clips it
does not hold, or a clip with no Hebrew or Russian text.

Usage:
  export MONGO_URI='mongodb+srv://survey_app:...@.../survey'
  python scripts/load_final.py ../user-survey/final_manifest.json [--retire-others]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from pymongo import MongoClient, UpdateOne


def check(m: dict) -> list[str]:
    errs = []
    clips = {c["clip_id"]: c for c in m["clips"]}
    for c in m["clips"]:
        if not (c.get("prompt_text_he") and c.get("prompt_text_ru")):
            errs.append(f"clip {c['clip_id']}: no Hebrew or Russian text")
    for p in m["pairs"]:
        if not {"pair_id", "a", "b", "prompt_key", "legs", "core"} <= set(p):
            errs.append(f"pair {p.get('pair_id')}: missing fields")
        elif not {p["a"], p["b"]} <= set(clips) or set(p["legs"]) != {p["a"], p["b"]}:
            errs.append(f"pair {p['pair_id']}: clips not in the manifest")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--db", default="survey")
    ap.add_argument("--retire-others", action="store_true")
    args = ap.parse_args()
    uri = os.environ.get("MONGO_URI")
    if not uri:
        print("set MONGO_URI", file=sys.stderr)
        return 2
    m = json.load(open(args.manifest))
    errs = check(m)
    if errs:
        print(f"{len(errs)} problem(s), e.g. {errs[0]}", file=sys.stderr)
        return 2
    db = MongoClient(uri)[args.db]
    db.final_clips.create_index("clip_id", unique=True)
    db.final_pairs.create_index("pair_id", unique=True)
    r = db.final_clips.bulk_write([UpdateOne({"clip_id": c["clip_id"]}, {"$set": {**c, "active": True}}, upsert=True)
                                   for c in m["clips"]])
    print(f"final_clips: {r.upserted_count} new, {r.modified_count} updated, {len(m['clips'])} in manifest")
    r = db.final_pairs.bulk_write([UpdateOne({"pair_id": p["pair_id"]}, {"$set": {**p, "active": True}}, upsert=True)
                                   for p in m["pairs"]])
    print(f"final_pairs: {r.upserted_count} new, {r.modified_count} updated, {len(m['pairs'])} in manifest "
          f"({sum(p['core'] for p in m['pairs'])} core)")
    if args.retire_others:
        r = db.final_pairs.update_many({"pair_id": {"$nin": [p["pair_id"] for p in m["pairs"]]}},
                                       {"$set": {"active": False}})
        print(f"retired {r.modified_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
