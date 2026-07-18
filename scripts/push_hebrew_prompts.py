#!/usr/bin/env python3
"""Push Hebrew prompt translations into the `pairs` collection.

Adds a `prompt_text_he` field to every pair, matched by its English `prompt_text`.
Translations live in app/i18n_prompts_he.json ({english: hebrew}).

Run with a FULL-ACCESS Mongo URI (the read-only survey URI can't write):

    export MONGO_URI='mongodb+srv://<user>:<pass>@survey-app.yjs8y8c.mongodb.net/'
    python scripts/push_hebrew_prompts.py            # apply
    python scripts/push_hebrew_prompts.py --dry-run  # report only, no writes

By default it refuses to run if any prompt in the DB lacks a translation
(so a stale JSON can't silently leave half the survey untranslated).
Pass --allow-missing to update whatever is covered anyway.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pymongo import MongoClient, UpdateMany

HE_JSON = Path(__file__).resolve().parent.parent / "app" / "i18n_prompts_he.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default=os.environ.get("MONGO_URI"),
                    help="Mongo URI (default: $MONGO_URI). Needs write access.")
    ap.add_argument("--db", default="survey")
    ap.add_argument("--dry-run", action="store_true", help="report only, no writes")
    ap.add_argument("--allow-missing", action="store_true",
                    help="proceed even if some DB prompts have no translation")
    args = ap.parse_args()

    if not args.uri:
        sys.exit("No Mongo URI. Set $MONGO_URI or pass --uri (must have write access).")

    translations: dict[str, str] = json.loads(HE_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(translations)} translations from {HE_JSON}")

    client = MongoClient(args.uri, serverSelectionTimeoutMS=15000,
                         uuidRepresentation="standard")
    pairs = client[args.db].pairs

    db_prompts = set(pairs.distinct("prompt_text"))
    missing = sorted(p for p in db_prompts if p not in translations)
    if missing:
        print(f"\n{len(missing)} DB prompt(s) have NO Hebrew translation:")
        for p in missing[:20]:
            print("  -", p)
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")
        if not args.allow_missing:
            sys.exit("\nRefusing to run. Fix the JSON, or pass --allow-missing.")

    unused = sorted(set(translations) - db_prompts)
    if unused:
        print(f"\nNote: {len(unused)} translation(s) don't match any current DB prompt "
              "(ignored).")

    # UpdateMany: each prompt maps to several pair docs (each prompt has multiple
    # arms/generators), so all of them must get the translation, not just the first.
    ops = [
        UpdateMany({"prompt_text": en}, {"$set": {"prompt_text_he": he}})
        for en, he in translations.items()
        if en in db_prompts
    ]
    print(f"\n{len(ops)} distinct prompt(s) to translate "
          f"(spanning {pairs.count_documents({})} pair docs).")

    if args.dry_run:
        print("Dry run - no writes performed.")
        return 0

    result = pairs.bulk_write(ops, ordered=False)
    print(f"Done. Matched {result.matched_count}, modified {result.modified_count} "
          "pair docs.")

    still_missing = pairs.count_documents({"prompt_text_he": {"$exists": False}})
    print(f"Pairs still without prompt_text_he: {still_missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
