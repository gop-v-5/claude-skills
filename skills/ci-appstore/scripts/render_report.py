#!/usr/bin/env python3
"""Render the App Store competitive report FROM the structured profiles.

The report is a pure view over data — no facts are authored here. It reads, from the
data directory:
  - profiles/*.json          (the source of truth)
  - config/competitors.yaml  (roster order, keyword set, depth dimensions, capability rows, score weights)
  - analysis/synthesis.json  (optional cross-competitor analysis: whitespace, radar, backlog)

and writes reports/<date>-<report_slug>.md. Weighted scores are COMPUTED here from
each profile's 1–5 sub-scores × the weights in config, so the weighting is consistent
and auditable rather than hand-typed into a table.

Usage:
  python3 scripts/render_report.py --date 2026-09-01
  python3 scripts/render_report.py --data-dir examples/demo --stdout
"""
import argparse
import json
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

try:
    import yaml
except ImportError:
    yaml = None

VERDICT_GLYPH = {
    "baseline_advantage": "✅",
    "parity": "➖",
    "competitor_advantage": "❌",
    "unknown": "❓",
    "irrelevant": "⬜",
}
FREQ_GLYPH = {"prominent": "●", "present": "○", "absent": "—"}
# "None" is a real depth verdict (the app doesn't do this job); spell it out so it
# can't be mistaken for missing data, which renders as "—".
DEPTH_LABEL = {"None": "Not offered"}


def load_json(p):
    with open(p) as f:
        return json.load(f)


def load_config(data_dir):
    if yaml is None:
        raise SystemExit("PyYAML required: pip install pyyaml")
    with open(data_dir / "config" / "competitors.yaml") as f:
        return yaml.safe_load(f)


def load_profiles(cfg, data_dir):
    """Return profiles in roster order (baseline first)."""
    order = [c["slug"] for c in cfg["competitors"]]
    profs = {}
    for p in (data_dir / "profiles").glob("*.json"):
        profs[p.stem] = load_json(p)
    ordered = [profs[s] for s in order if s in profs]
    # any profile not in config roster appended at the end
    ordered += [profs[s] for s in sorted(profs) if s not in order]
    return ordered


def app_store(p):
    return (p.get("layers") or {}).get("app_store") or {}


def weighted(subscores, weights):
    if not subscores:
        return None
    vals = [(subscores.get(k), w) for k, w in weights.items()]
    if any(v is None for v, _ in vals):
        return None
    return round(sum(v * w for v, w in vals), 2)


def name(p):
    return p.get("identity", {}).get("name", p.get("slug", "?"))


def baseline_name(profs):
    return next((name(p) for p in profs if p.get("is_baseline")), "the baseline app")


def label(key):
    return key.replace("_", " ")


# ---------------------------------------------------------------- sections ----
def sec_header(profs, cfg, date):
    n_comp = sum(0 if p.get("is_baseline") else 1 for p in profs)
    total_claims = sum(len(p.get("claims", [])) for p in profs)
    verified = sum(
        1 for p in profs for c in p.get("claims", []) if c.get("verification") == "verified"
    )
    return [
        f"# Competitive Intelligence — Shopify App Store: {baseline_name(profs)} vs {n_comp} competitors",
        "",
        f"*Generated {date} from {len(profs)} structured profiles "
        f"({n_comp} competitors + baseline). "
        f"{verified}/{total_claims} claims independently verified. "
        "Rendered by scripts/render_report.py — do not hand-edit; edit the profiles and re-render.*",
        "",
    ]


def sec_landscape(profs, cfg):
    dims = cfg.get("depth_dimensions") or []
    lines = ["## 1. The competitive landscape in one page", "",
             "| App | Threat | Rating / reviews | Entry price | "
             + "".join(f"Depth: {label(d)} | " for d in dims) + "Trajectory |",
             "|---|---|---|---|" + "---|" * len(dims) + "---|"]
    for p in profs:
        a = app_store(p)
        rv, pr, po = a.get("reviews", {}), a.get("pricing", {}), a.get("positioning", {})
        depth = a.get("capabilities", {}).get("depth", {})
        tiers = pr.get("tiers") or []
        entry = next((t for t in tiers if (t.get("monthly_usd") or 0) > 0 or t.get("variable_fee")), tiers[0] if tiers else {})
        entry_str = "—"
        if entry:
            price = f"${entry.get('monthly_usd')}" if entry.get("monthly_usd") is not None else "Free"
            entry_str = price + (f" {entry.get('variable_fee')}" if entry.get("variable_fee") else "")
        rating = f"{rv.get('rating','?')}★ / {rv.get('count','?')}"
        tag = "**" + name(p) + "**" + (" (baseline)" if p.get("is_baseline") else "")
        depth_cells = "".join(f"{DEPTH_LABEL.get(depth.get(d), depth.get(d)) or '—'} | " for d in dims)
        lines.append(f"| {tag} | {po.get('threat_type') or '—'} | {rating} | {entry_str} | "
                     f"{depth_cells}{po.get('trajectory') or '—'} |")
    lines.append("")
    return lines


def sec_scores(profs, cfg):
    views = [
        ("2. Scoring — merchant purchase-decision view", "merchant_decision",
         cfg["scoring"]["merchant_decision"]),
        ("3. Scoring — strategic competitive-strength view", "strategic_strength",
         cfg["scoring"]["strategic_strength"]),
    ]
    lines = []
    for title, key, weights in views:
        cols = list(weights.keys())
        lines += [f"## {title}", "",
                  "| App | " + " | ".join(label(c) for c in cols) + " | **Weighted** |",
                  "|---|" + "---|" * (len(cols) + 1)]
        rows = []
        for p in profs:
            sub = (p.get("scores") or {}).get(key) or {}
            if not sub:
                continue
            w = weighted(sub, weights)
            rows.append((w if w is not None else -1, p, sub, w))
        for _, p, sub, w in sorted(rows, key=lambda r: r[0], reverse=True):
            cells = " | ".join(str(sub.get(c, "–")) for c in cols)
            tag = "**" + name(p) + "**" if p.get("is_baseline") else name(p)
            lines.append(f"| {tag} | {cells} | **{w if w is not None else '–'}** |")
        lines += ["", "*Weights (from config): "
                  + ", ".join(f"{k} {int(round(v * 100))}%" for k, v in weights.items()) + ".*", ""]
    return lines


def sec_appstore_compare(profs):
    lines = ["## 4. App Store listing comparison", "",
             "| App | Name strategy | Badges | Rating × reviews | Subtitle strategy |",
             "|---|---|---|---|---|"]
    for p in profs:
        a = app_store(p)
        lst, rv = a.get("listing", {}), a.get("reviews", {})
        badges = ", ".join(lst.get("badges", [])) or "—"
        lines.append(f"| {name(p)} | {lst.get('name_strategy') or '—'} | {badges} | "
                     f"{rv.get('rating','?')} × {rv.get('count','?')} | {lst.get('subtitle_strategy') or '—'} |")
    lines.append("")
    return lines


def sec_pricing(profs):
    lines = ["## 5. Pricing & packaging board", "",
             "| App | Free? | Model | Tiers (monthly) | Variable component |",
             "|---|---|---|---|---|"]
    for p in profs:
        pr = app_store(p).get("pricing", {})
        free = "Yes" if pr.get("has_free_plan") else ("No" if pr.get("has_free_plan") is False else "?")
        if pr.get("has_free_plan") and pr.get("free_includes_core_job") is False:
            free += " (core job is paid)"
        tiers = " · ".join(
            (f"${t['monthly_usd']}" if t.get("monthly_usd") is not None else "Free")
            + (f" {t['variable_fee']}" if t.get("variable_fee") else "")
            for t in (pr.get("tiers") or [])
        ) or "—"
        lines.append(f"| {name(p)} | {free} | {pr.get('model_category') or '—'} | {tiers} | "
                     f"{pr.get('variable_component') or '—'} |")
    lines.append("")
    return lines


def sec_complaints(profs):
    themes, seen = [], set()
    for p in profs:
        for ct in app_store(p).get("reviews", {}).get("complaint_themes", []):
            t = ct.get("theme")
            if t and t not in seen:
                seen.add(t)
                themes.append(t)
    if not themes:
        return []
    header = "| Complaint theme | " + " | ".join(name(p) for p in profs) + " |"
    lines = ["## 6. Voice-of-customer — complaint-frequency matrix", "",
             "*● prominent · ○ present · — not observed*", "",
             header, "|---|" + "---|" * len(profs)]
    for t in themes:
        row = [t]
        for p in profs:
            m = {c["theme"]: c["frequency"] for c in app_store(p).get("reviews", {}).get("complaint_themes", [])}
            row.append(FREQ_GLYPH.get(m.get(t), "—"))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def sec_keywords(profs, cfg):
    terms = cfg["keyword_audit"]
    header = "| Keyword | " + " | ".join(name(p) for p in profs) + " |"
    lines = ["## 7. App Store keyword-visibility grid", "",
             "*Search rank per term; · = not in observed top set.*", "",
             header, "|---|" + "---|" * len(profs)]
    for t in terms:
        row = [t]
        for p in profs:
            r = app_store(p).get("keyword_visibility", {}).get(t)
            row.append(f"#{r}" if isinstance(r, int) else "·")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def sec_capabilities(profs, cfg):
    comps = [p for p in profs if not p.get("is_baseline")]
    if not comps:
        return []
    base = baseline_name(profs)
    header = f"| Capability (vs {base}) | " + " | ".join(name(p) for p in comps) + " |"
    lines = [f"## 8. Product capability matrix vs {base}", "",
             f"*✅ {base} ahead · ➖ parity · ❌ competitor ahead · ❓ unknown · ⬜ n/a*", "",
             header, "|---|" + "---|" * len(comps)]
    for cap in cfg["capability_rows"]:
        row = [label(cap)]
        for p in comps:
            v = app_store(p).get("capabilities", {}).get("matrix", {}).get(cap)
            row.append(VERDICT_GLYPH.get(v, "❓"))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def sec_how_they_win(profs):
    lines = ["## 9. How each competitor is trying to win", ""]
    for p in profs:
        if p.get("is_baseline"):
            continue
        po = app_store(p).get("positioning", {})
        if po.get("how_they_win"):
            lvl = f" ({po['threat_level']})" if po.get("threat_level") else ""
            lines.append(f"**{name(p)}.** {po['how_they_win']}{lvl}")
            lines.append("")
    return lines


def sec_battlecards(profs, synth):
    counters = (synth or {}).get("battlecard_counters", {})
    lines = ["## 10. Competitive battlecards", ""]
    for p in profs:
        if p.get("is_baseline"):
            continue
        po = app_store(p).get("positioning", {})
        lines += [f"### {name(p)}",
                  f"- **Threat:** {po.get('threat_type') or '—'} ({po.get('threat_level') or '—'})",
                  f"- **How they win:** {po.get('implied_positioning') or po.get('how_they_win') or '—'}"]
        if counters.get(p["slug"]):
            lines.append(f"- **Our counter:** {counters[p['slug']]}")
        lines.append("")
    return lines


def sec_synthesis(synth):
    if not synth:
        return ["## 11. Analyst synthesis", "",
                "*No analysis/synthesis.json found — run the analyze stage to populate whitespace, "
                "threat radar, and the action backlog.*", ""]
    lines = ["## 11. Analyst synthesis", ""]
    if synth.get("landscape_summary"):
        lines += ["### Landscape summary"] + [f"- {b}" for b in synth["landscape_summary"]] + [""]
    if synth.get("whitespace"):
        lines += ["### Market whitespace"] + [f"- {b}" for b in synth["whitespace"]] + [""]
    if synth.get("threat_radar"):
        lines += ["### Threat & opportunity radar", "", "| Item | Type | Level |", "|---|---|---|"]
        lines += [f"| {r.get('item','')} | {r.get('type','')} | {r.get('level','')} |" for r in synth["threat_radar"]]
        lines.append("")
    bl = synth.get("backlog", {})
    if bl:
        for key, title in [("d0_30", "0–30 day quick wins"), ("m1_3", "1–3 month"), ("m3_12", "3–12 month bets")]:
            if bl.get(key):
                lines += [f"### Actions — {title}"] + [f"- {b}" for b in bl[key]] + [""]
    if synth.get("recommended_strategy"):
        lines += ["### Recommended strategy"] + [f"- {b}" for b in synth["recommended_strategy"]] + [""]
    return lines


def sec_evidence(profs):
    lines = ["## 12. Evidence & provenance appendix", "",
             "| App | Claims | verified | unverified | refuted | stale |",
             "|---|---|---|---|---|---|"]
    for p in profs:
        c = p.get("claims", [])
        counts = {k: sum(1 for x in c if x.get("verification") == k)
                  for k in ("verified", "unverified", "refuted", "stale")}
        lines.append(f"| {name(p)} | {len(c)} | {counts['verified']} | {counts['unverified']} "
                     f"| {counts['refuted']} | {counts['stale']} |")
    lines.append("")
    return lines


def render(data_dir, date):
    cfg = load_config(data_dir)
    profs = load_profiles(cfg, data_dir)
    if not profs:
        raise SystemExit(f"No profiles found in {data_dir / 'profiles'} — run the collect stage first.")
    synth_path = data_dir / "analysis" / "synthesis.json"
    synth = load_json(synth_path) if synth_path.exists() else None

    out = []
    out += sec_header(profs, cfg, date)
    out += sec_landscape(profs, cfg)
    out += sec_scores(profs, cfg)
    out += sec_appstore_compare(profs)
    out += sec_pricing(profs)
    out += sec_complaints(profs)
    out += sec_keywords(profs, cfg)
    out += sec_capabilities(profs, cfg)
    out += sec_how_they_win(profs)
    out += sec_battlecards(profs, synth)
    out += sec_synthesis(synth)
    out += sec_evidence(profs)
    return cfg, "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=str(SKILL_DIR),
                    help="folder holding config/, profiles/, analysis/ and reports/ (default: the skill folder)")
    ap.add_argument("--date", default="undated")
    ap.add_argument("--stdout", action="store_true", help="print the report instead of writing a file")
    args = ap.parse_args()

    data_dir = Path(args.data_dir).resolve()
    cfg, md = render(data_dir, args.date)
    if args.stdout:
        print(md, end="")
        return
    reports = data_dir / "reports"
    reports.mkdir(exist_ok=True)
    slug = cfg.get("refresh", {}).get("report_slug", "appstore")
    dest = reports / f"{args.date}-{slug}.md"
    dest.write_text(md)
    print(f"Wrote {dest} ({len(md.splitlines())} lines)")


if __name__ == "__main__":
    main()
