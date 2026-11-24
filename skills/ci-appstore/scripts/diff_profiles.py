#!/usr/bin/env python3
"""Diff competitor profiles between two points in time (refresh support).

Before a refresh, snapshot profiles/ -> snapshots/<date>/. After re-collecting, this
reports what MATERIALLY changed per app — the signal a merchant/strategist cares
about, not JSON noise: pricing tiers & model, free-plan flag, rating, review count &
velocity, keyword ranks, new/resolved complaint themes, capability verdicts, and
score movements.

Usage:
  python3 scripts/diff_profiles.py snapshots/2026-08-01                 # snapshot vs current profiles/
  python3 scripts/diff_profiles.py snapshots/2026-08-01 path/to/profiles   # explicit old vs new
  python3 scripts/diff_profiles.py examples/demo/snapshots/2026-08-01 examples/demo/profiles
"""
import argparse
import json
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_dir(d):
    d = Path(d)
    return {p.stem: json.loads(p.read_text()) for p in d.glob("*.json")}


def app_store(p):
    return (p.get("layers") or {}).get("app_store") or {}


def pricing_signature(p):
    pr = app_store(p).get("pricing", {})
    tiers = tuple((t.get("name"), t.get("monthly_usd"), t.get("variable_fee")) for t in (pr.get("tiers") or []))
    return (pr.get("has_free_plan"), pr.get("model_category"), tiers)


def diff_one(slug, old, new):
    changes = []
    ao, an = app_store(old), app_store(new)

    if pricing_signature(old) != pricing_signature(new):
        po, pn = ao.get("pricing", {}), an.get("pricing", {})
        fo = lambda pr: " · ".join(
            (f"${t.get('monthly_usd')}" if t.get("monthly_usd") is not None else "Free")
            + (f" {t['variable_fee']}" if t.get("variable_fee") else "") for t in (pr.get("tiers") or [])) or "—"
        changes.append(f"PRICING: {fo(po)}  ->  {fo(pn)}")
        if po.get("has_free_plan") != pn.get("has_free_plan"):
            changes.append(f"  free plan: {po.get('has_free_plan')} -> {pn.get('has_free_plan')}")

    ro, rn = ao.get("reviews", {}), an.get("reviews", {})
    if ro.get("rating") != rn.get("rating"):
        changes.append(f"RATING: {ro.get('rating')} -> {rn.get('rating')}")
    if ro.get("count") != rn.get("count"):
        d = (rn.get("count") or 0) - (ro.get("count") or 0)
        changes.append(f"REVIEWS: {ro.get('count')} -> {rn.get('count')} ({d:+d})")
    if ro.get("velocity_per_month") != rn.get("velocity_per_month"):
        changes.append(f"VELOCITY: {ro.get('velocity_per_month')} -> {rn.get('velocity_per_month')} /mo")

    ko, kn = ao.get("keyword_visibility", {}), an.get("keyword_visibility", {})
    for term in sorted(set(ko) | set(kn)):
        if ko.get(term) != kn.get(term):
            changes.append(f"KEYWORD '{term}': #{ko.get(term)} -> #{kn.get(term)}")

    to = {c["theme"] for c in ro.get("complaint_themes", [])}
    tn = {c["theme"] for c in rn.get("complaint_themes", [])}
    for t in sorted(tn - to):
        changes.append(f"NEW complaint theme: {t}")
    for t in sorted(to - tn):
        changes.append(f"RESOLVED complaint theme: {t}")

    mo = ao.get("capabilities", {}).get("matrix", {})
    mn = an.get("capabilities", {}).get("matrix", {})
    for cap in sorted(set(mo) | set(mn)):
        if mo.get(cap) != mn.get(cap):
            changes.append(f"CAPABILITY '{cap}': {mo.get(cap)} -> {mn.get(cap)}")

    for view in ("merchant_decision", "strategic_strength"):
        so = (old.get("scores") or {}).get(view) or {}
        sn = (new.get("scores") or {}).get(view) or {}
        for k in sorted(set(so) | set(sn)):
            if so.get(k) != sn.get(k):
                changes.append(f"SCORE {view}.{k}: {so.get(k)} -> {sn.get(k)}")

    return changes


def main():
    ap = argparse.ArgumentParser(description="Show what materially changed between two profile sets.")
    ap.add_argument("old", help="older profiles folder, e.g. snapshots/<date>")
    ap.add_argument("new", nargs="?", default=str(SKILL_DIR / "profiles"),
                    help="newer profiles folder (default: the skill's profiles/)")
    args = ap.parse_args()
    old = load_dir(args.old)
    new = load_dir(args.new)

    print(f"Diff: {args.old}  ->  {args.new}\n")
    any_change = False
    for slug in sorted(set(old) | set(new)):
        if slug not in old:
            print(f"+ NEW competitor: {slug}\n")
            any_change = True
            continue
        if slug not in new:
            print(f"- REMOVED competitor: {slug}\n")
            any_change = True
            continue
        changes = diff_one(slug, old[slug], new[slug])
        if changes:
            any_change = True
            print(f"● {new[slug].get('identity', {}).get('name', slug)}")
            for c in changes:
                print(f"    {c}")
            print()
    if not any_change:
        print("No material changes.")


if __name__ == "__main__":
    main()
