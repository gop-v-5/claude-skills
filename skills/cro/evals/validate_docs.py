#!/usr/bin/env python3
"""Static consistency checks for the CRO skill's docs. No model calls.

Complements the eval suite: `run_evals.py` grades what the model *produces*,
this asserts the skill's own files agree with each other before a run starts.

Covers three classes:

  1. Internal arithmetic in `references/page-profile-schema.md`'s worked example
     (LIFT totals, PXL subtotals, deltas, cross-references).
  2. Cross-file contracts (status vocabulary shared by SKILL.md and the schema;
     every reference SKILL.md loads is injected by run_evals.py).
  3. **Prose restating a machine-checkable fact.** This class is why the file
     exists: an earlier validator asserted the status *set* matched across files
     and passed, while the sentence "exactly these nine values" sat two lines
     above a list of ten. Counts, date-window labels and status lists written
     out in prose are checked against the thing they describe.

Usage:  python3 evals/validate_docs.py     (exit 0 = clean)
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_MD = SKILL_DIR / "references" / "page-profile-schema.md"
SKILL_MD = SKILL_DIR / "SKILL.md"
README_MD = SKILL_DIR / "README.md"
REPORT_MD = SKILL_DIR / "assets" / "report-template.md"
PXL_MD = SKILL_DIR / "references" / "pxl-prioritization.md"
RUN_EVALS = SKILL_DIR / "evals" / "run_evals.py"
GRADE_EVALS = SKILL_DIR / "evals" / "grade_evals.py"
HARNESS_CONFIG = SKILL_DIR / "evals" / "harness_config.py"
RUN_LOOP = SKILL_DIR / "run_loop.py"
PROFILE_STORE = SKILL_DIR / "scripts" / "profile_store.py"

STATUSES = {
    "proposed", "ready", "blocked_by_engineering", "needs_data",
    "running", "won", "lost", "inconclusive", "shipped", "abandoned",
}
SKILL_SETTABLE = {"proposed", "ready", "blocked_by_engineering", "needs_data"}

PXL_POINTS = {
    "potential": {"above_fold": 1, "noticeable_5s": 1, "added_or_removed": 1,
                  "high_traffic": 2, "known_conversion_problem": 1},
    "importance": {"top5_traffic": 2, "top5_conversion_value": 2, "must_interact": 1},
    "ease": {"no_dev_time": 1, "ships_this_sprint": 1, "no_third_party": 1},
    "evidence": {"qualitative": 1, "quantitative": 1},
}
NUMBER_WORDS = {
    5: "five", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    14: "fourteen", 15: "fifteen",
}

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok    {label}")
    else:
        failures.append(f"{label}{' — ' + detail if detail else ''}")
        print(f"  FAIL  {label}{' — ' + detail if detail else ''}")


def tier(score: int) -> str:
    return "P0" if score >= 13 else "P1" if score >= 9 else "P2" if score >= 5 else "P3"


def json_blocks(text: str) -> list[dict]:
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text, re.S)]


def days_inclusive(start: str, end: str) -> int:
    a = datetime.date.fromisoformat(start)
    b = datetime.date.fromisoformat(end)
    return (b - a).days + 1


def main() -> int:
    schema_src = SCHEMA_MD.read_text()
    skill_src = SKILL_MD.read_text()
    readme_src = README_MD.read_text()
    report_src = REPORT_MD.read_text()

    docs = json_blocks(schema_src)
    d = docs[0]
    latest = d["latest"]

    print("\n== example arithmetic ==")
    lift = latest["lift"]
    check("lift.total equals sum of factors",
          lift["total"] == sum(f["score"] for f in lift["factors"].values()))
    check("lift.max is 30", lift["max"] == 30)
    bad = {k: f["score"] for k, f in lift["factors"].items() if not 1 <= f["score"] <= 5}
    check("every LIFT factor scores 1-5", not bad, str(bad))
    lowest = sorted(lift["factors"], key=lambda k: lift["factors"][k]["score"])[:2]
    check("lowest_two matches the two lowest factors",
          set(lift["lowest_two"]) == set(lowest))

    mode = latest["pxl"]["scoring_mode"]
    check("full worked example carries the required 5–8 PXL ideas",
          latest["scope"] != "full" or 5 <= len(latest["pxl"]["ideas"]) <= 8,
          f"found {len(latest['pxl']['ideas'])}")
    for idea in latest["pxl"]["ideas"]:
        tag = idea["experiment_id"]
        total = unknown = 0
        for group, crit in PXL_POINTS.items():
            blk = idea["criteria"][group]
            check(f"{tag}.{group} subtotal",
                  blk["subtotal"] == sum(p for k, p in crit.items() if blk[k] is True))
            check(f"{tag}.{group} max", blk["max"] == sum(crit.values()))
            total += blk["subtotal"]
            unknown += sum(p for k, p in crit.items() if blk[k] is None)
        check(f"{tag}.score", idea["score"] == total)
        check(f"{tag}.unknown_points", idea["unknown_points"] == unknown)
        check(f"{tag}.max_achievable", idea["max_achievable"] == 16 - unknown)
        expected = None if mode == "heuristic_only" else tier(idea["score"])
        check(f"{tag}.priority ({'null in heuristic-only' if expected is None else expected})",
              idea["priority"] == expected)

    print("\n== history provenance (focused runs must not launder stale data) ==")
    for snap in d["history"] + [x for x in docs[1:] if "measured" in x]:
        sid = snap["audit_id"]
        check(f"{sid} declares measured for all four blocks",
              set(snap["measured"]) == {"page_snapshot", "metrics", "lift", "pxl"})
        for block, key in (("metrics", "key_metrics"), ("lift", "lift"),
                           ("pxl", "pxl"), ("page_snapshot", "page_snapshot")):
            if not snap["measured"][block]:
                check(f"{sid}.{block} unmeasured -> stored null",
                      snap.get(key) is None,
                      "carried value copied into history under the wrong audit_id")
            else:
                check(f"{sid}.{block} measured -> stored", snap.get(key) is not None)
        if snap["measured"]["page_snapshot"] and isinstance(snap.get("page_snapshot"), dict):
            check(f"{sid}.page_snapshot carries redesign-check fields",
                  set(snap["page_snapshot"]) == {"headline", "primary_cta_text"})
        if snap["measured"]["lift"] and isinstance(snap.get("lift"), dict):
            check(f"{sid}.lift.total equals sum of factors",
                  snap["lift"]["total"] == sum(snap["lift"]["factors"].values()))

    print("\n== per-block delta sourcing ==")
    chg = latest["changes_since_previous"]
    check("has compared_against", "compared_against" in chg)
    check("has not_compared", "not_compared" in chg)
    hist_ids = {h["audit_id"] for h in d["history"]}
    for block, target in chg["compared_against"].items():
        check(f"compared_against.{block} resolves to a real snapshot",
              target is None or target in hist_ids, str(target))
    for block, delta_key in (("lift", "lift_deltas"), ("metrics", "metric_deltas")):
        if chg.get(delta_key):
            src = latest[block]
            check(f"{delta_key} only emitted when {block} measured this run",
                  src["observed_in"] == latest["audit_id"])
            check(f"{delta_key} has a compared_against target",
                  chg["compared_against"][block] is not None)

    print("\n== changes_since_previous roll-up ==")
    ROLLUP_FIELDS = ("lift_total_delta", "lift_deltas", "metric_deltas",
                     "new_experiments", "recurring_experiments", "dropped_experiments",
                     "rank_changes", "new_issues", "resolved_issues")
    check("roll-up carries every documented field",
          all(f in chg for f in ROLLUP_FIELDS),
          f"missing: {[f for f in ROLLUP_FIELDS if f not in chg]}")
    check("lift_deltas sum to lift_total_delta",
          sum(chg["lift_deltas"].values()) == chg["lift_total_delta"],
          f"{sum(chg['lift_deltas'].values())} vs {chg['lift_total_delta']}")
    # `dropped_experiments` means "fell out of the ranking while still eligible".
    # A settled or in-flight test is SUPPOSED to be absent — SKILL.md Step 2
    # suppresses it — so listing it would report correct behaviour as a
    # regression. This is the trap the field rule exists to close.
    SETTLED = {"won", "lost", "shipped", "running", "abandoned"}
    status_of = {e["id"]: e["status"] for e in d["experiments"]}
    ranked_now = {i["experiment_id"] for i in latest["pxl"]["ideas"]}
    prev = next((h for h in d["history"] if h["audit_id"] == chg["compared_to"]), None)
    check("compared_to resolves to a history snapshot", prev is not None)
    for eid in (prev or {}).get("pxl", {}).get("top_3", []):
        if eid in ranked_now:
            continue
        if status_of.get(eid) in SETTLED:
            check(f"{eid} ({status_of.get(eid)}) suppressed, not reported dropped",
                  eid not in chg["dropped_experiments"])
        else:
            check(f"{eid} ({status_of.get(eid)}) fell out while eligible -> dropped",
                  eid in chg["dropped_experiments"])

    print("\n== cross-references ==")
    exp_ids = {e["id"] for e in d["experiments"]}
    check("no duplicate experiment ids", len(exp_ids) == len(d["experiments"]))
    check("every ranked idea has an experiments[] entry",
          all(i["experiment_id"] in exp_ids for i in latest["pxl"]["ideas"]))
    for field in ("new_experiments", "recurring_experiments", "dropped_experiments"):
        check(f"{field} all resolve", all(x in exp_ids for x in chg[field]))
    issue_ids = {e["id"] for e in d["engineering_issues"]}
    check("issue references resolve",
          all(x in issue_ids for x in chg["new_issues"] + chg["resolved_issues"]))
    blocked = {x for e in d["engineering_issues"]
               if e["severity"] == "Sev0" and e["status"] == "open"
               for x in e["blocks_experiments"]}
    check("experiments blocked by an open Sev0 say so",
          all(e["status"] == "blocked_by_engineering"
              for e in d["experiments"] if e["id"] in blocked))

    print("\n== status vocabulary ==")
    for e in d["experiments"]:
        check(f"{e['id']} status is in the vocabulary", e["status"] in STATUSES, e["status"])
        if e["status_source"] == "audit":
            check(f"{e['id']} skill-set status is skill-settable",
                  e["status"] in SKILL_SETTABLE, e["status"])
        if e["status"] == "shipped":
            check(f"{e['id']} shipped implies a recorded outcome",
                  e.get("outcome") is not None)
    found = lambda src: {m for m in STATUSES if f"`{m}`" in src}
    check("SKILL.md uses no status outside the vocabulary",
          found(skill_src) <= STATUSES)
    check("SKILL.md and schema agree on the full set",
          found(skill_src) == found(schema_src) == STATUSES,
          f"skill={sorted(found(skill_src))} schema={sorted(found(schema_src))}")

    print("\n== prose restating a checkable fact ==")
    m = re.search(r"exactly these (\w+) values", schema_src)
    check("schema's spelled-out status count matches the vocabulary",
          bool(m) and m.group(1) == NUMBER_WORDS[len(STATUSES)],
          f"prose says '{m.group(1) if m else '?'}', vocabulary has {len(STATUSES)}")

    # Same class as the status count above, for the roll-up. Both of these were
    # wrong when the paragraph was written ("fifteen" for 14 fields, "six" for
    # 5 ID lists) and passed every check, because the existing guard only
    # regexes the one "exactly these N values" phrase.
    m = re.search(r"all (\w+) fields shown in the worked example", schema_src)
    check("schema's spelled-out roll-up field count matches the worked example",
          bool(m) and m.group(1) == NUMBER_WORDS[len(chg)],
          f"prose says '{m.group(1) if m else '?'}', example has {len(chg)}")
    id_lists = [k for k in chg
                if k.endswith("_experiments") or k.endswith("_issues")]
    m = re.search(r"The (\w+) ID lists", schema_src)
    check("schema's spelled-out ID-list count matches the worked example",
          bool(m) and m.group(1) == NUMBER_WORDS[len(id_lists)],
          f"prose says '{m.group(1) if m else '?'}', example has {len(id_lists)}: {sorted(id_lists)}")

    windows = re.findall(
        r'"start":\s*"(\d{4}-\d{2}-\d{2})",\s*"end":\s*"(\d{4}-\d{2}-\d{2})",\s*"label":\s*"last (\d+) days"',
        schema_src.replace("\n", " "))
    check("schema example date windows exist", bool(windows))
    for start, end, label in windows:
        check(f"window {start}..{end} really is {label} days",
              days_inclusive(start, end) == int(label),
              f"{days_inclusive(start, end)} days inclusive")
    readme_claim = re.search(
        r"only ever assigns four audit-owned statuses:(.*?)Anything past that",
        readme_src, re.S)
    readme_statuses = (
        {status for status in SKILL_SETTABLE if f"`{status}`" in readme_claim.group(1)}
        if readme_claim else set()
    )
    check("README's list of skill-settable statuses is complete and correct",
          bool(readme_claim) and readme_statuses == SKILL_SETTABLE,
          str(sorted(readme_statuses)) if readme_claim else "claim not found")
    check("schema title uses the actual profile filename contract",
          schema_src.startswith("# Page Profile Schema (`profiles/<slug>.json`)")
          and "`page_profile.json`" not in schema_src)

    print("\n== report/schema contract ==")
    check("report-template tells the reader not to assign a tier in heuristic-only mode",
          "n/a (heuristic-only)" in report_src)
    check("pxl-prioritization's presentation block carries the same caveat",
          "n/a (heuristic-only)" in PXL_MD.read_text())

    print("\n== recovery contract ==")
    # A corrupt or newer-schema profile must be preserved and written beside,
    # never overwritten — and the recovery name must be unique on its own, not
    # derived from the unreadable file's audit_id (which caused a clobber bug).
    check("schema routes all writes through the deterministic helper",
          "All profile writes go through `scripts/profile_store.py`" in schema_src)
    check("schema documents an atomic no-clobber recovery write",
          "atomic exclusive-create operation" in schema_src
          and "never performs a check-then-overwrite sequence" in schema_src)
    check("recovery covers both corrupt and unsupported-version kinds",
          "kind `corrupt`" in schema_src and "kind `unsupported-version`" in schema_src)
    check("recovery filename is timestamped, independent of audit_id",
          ".<kind>-<YYYYMMDD-HHMMSS>.json" in schema_src
          and "corrupt-<audit_id>" not in schema_src,
          "recovery name still tied to audit_id")
    check("recovery escalates with a numeric suffix on collision",
          "`-2`, then `-3`" in schema_src)
    check("recovery constructs a complete standalone current-run profile",
          "Construct a complete current-run profile in memory" in schema_src
          and "set `history: []`" in schema_src
          and "omit `changes_since_previous`" in schema_src)
    check("normal writes use fingerprint conflict detection and atomic replacement",
          "expected_fingerprint" in schema_src
          and "`CONFLICT` (exit `3`)" in schema_src
          and "`VERSION` (exit `4`)" in schema_src
          and "replaces the canonical file atomically" in schema_src)
    check("schema documents strict first-write provenance",
          "There is no older canonical evidence from which a first write may claim "
          "inherited history or prior provenance" in schema_src
          and "Apply the same current-audit provenance rules" in schema_src)
    check("schema documents future audit rejection",
          "rejects a `latest.audit_id` later than the machine's local current date"
          in schema_src)
    check("schema locks carried latest blocks to the canonical value",
          "leave the prior block exactly equal to the locked canonical value"
          in schema_src
          and "Changing any nested value or deleting/nulling the carried block is rejected"
          in schema_src)
    check("schema documents exact PXL criteria and compactable measured metrics",
          "contains exactly that group's documented criterion keys" in schema_src
          and "current metrics block marked as measured must already contain at least one "
          "finite, unambiguous numeric leaf" in schema_src)

    print("\n== experiment and engineering reconciliation ==")
    check("audit-owned experiment status refreshes from the current section 6 row",
          "replace its stale status with this run's audit-owned status" in schema_src)
    check("new experiments persist the current audit-owned status",
          'append with the audit-owned status and `status_source: "audit"`' in schema_src)
    check("user-reported experiment state remains protected",
          "Preserve a `user_reported` status/outcome" in schema_src)
    check("engineering issues carry stable check ids",
          "Every `engineering_issues[]` entry carries a stable" in schema_src
          and all(issue.get("check_id") for issue in d["engineering_issues"]))
    checks_run = set(latest.get("engineering_checks_run", []))
    for issue in d["engineering_issues"]:
        if issue["first_seen"] == latest["audit_id"] or issue.get("resolved_in_audit") == latest["audit_id"]:
            check(f"{issue['id']} was actually checked in the current audit",
                  issue["check_id"] in checks_run, issue["check_id"])
    check("issue resolution requires the exact completed check",
          "only when its exact prior `check_id` appears" in schema_src)

    print("\n== atomic profile-store helper ==")
    check("profile_store.py exists", PROFILE_STORE.exists())
    spec = importlib.util.spec_from_file_location("cro_profile_store", PROFILE_STORE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        # The production helper binds writes to <skill-dir>/profiles. Redirect
        # that store into this isolated fixture rather than weakening the guard.
        module.PROFILE_DIR = root / "profiles"
        # Named for the worked example's own slug, not a generic stub: the
        # helper now refuses to file a payload under any other slug, which is
        # the whole point of the guard.
        canonical = root / "profiles" / f"{d['page']['slug']}.json"

        def clone(obj):
            return json.loads(json.dumps(obj))

        def as_first_audit(candidate):
            """Remove every claim that depends on an earlier canonical profile."""
            out = clone(candidate)
            audit_id = out["latest"]["audit_id"]
            out["history"] = []
            out["latest"].pop("changes_since_previous", None)
            for block in module.BLOCKS:
                value = out["latest"].get(block)
                if isinstance(value, dict):
                    value["observed_in"] = audit_id
            for experiment in out["experiments"]:
                if isinstance(experiment, dict):
                    experiment["created_in_audit"] = audit_id
                    experiment["last_seen_in_audit"] = audit_id
            for issue in out["engineering_issues"]:
                if isinstance(issue, dict):
                    issue["first_seen"] = audit_id
                    issue["last_seen"] = audit_id
                    if issue.get("status") == "fixed":
                        issue["status"] = "open"
                        issue["resolved_in_audit"] = None
            return out

        def make_reaudit(prior_profile, audit_id=None):
            """Build one valid no-change re-audit from an authenticated canonical."""
            audit_id = audit_id or datetime.date.today().isoformat()
            candidate = clone(prior_profile)
            prior_latest = prior_profile["latest"]
            candidate["history"] = [
                module.compact_latest_snapshot(
                    prior_latest,
                    prior_profile["engineering_issues"],
                ),
                *clone(prior_profile["history"][:11]),
            ]
            candidate["latest"].update(
                audit_id=audit_id,
                audited_at=audit_id[:10],
                engineering_checks_run_observed_in=audit_id,
            )
            for block in ("page_snapshot", "metrics", "lift", "pxl"):
                if isinstance(candidate["latest"].get(block), dict):
                    candidate["latest"][block]["observed_in"] = audit_id

            current_ids = {
                idea["experiment_id"]
                for idea in candidate["latest"]["pxl"]["ideas"]
            }
            prior_compact_ids = {
                idea["experiment_id"]
                for idea in prior_latest["pxl"]["ideas"][:3]
            }
            for experiment in candidate["experiments"]:
                if experiment["id"] in current_ids:
                    experiment["last_seen_in_audit"] = audit_id

            candidate["latest"]["changes_since_previous"] = {
                "compared_to": prior_latest["audit_id"],
                "compared_against": {
                    "metrics": prior_latest["audit_id"],
                    "lift": prior_latest["audit_id"],
                    "pxl": prior_latest["audit_id"],
                },
                "not_compared": [],
                "comparable": True,
                "comparability_note": (
                    "Same scoring mode, analytics window, and contributing "
                    "data-layer availability."
                ),
                "lift_total_delta": 0,
                "lift_deltas": {name: 0 for name in module.LIFT_FACTORS},
                # The schema permits a compact subset of comparable metrics,
                # including the empty subset.
                "metric_deltas": {},
                "new_experiments": [],
                "recurring_experiments": sorted(
                    current_ids & prior_compact_ids),
                "dropped_experiments": [],
                "rank_changes": {},
                "new_issues": [],
                "resolved_issues": [],
            }
            return candidate

        def rejected(candidate, mode="canonical"):
            """True when the helper refuses to persist *candidate*."""
            try:
                module.validate_profile(candidate, mode)
                return False
            except module.ProfileInvalidError:
                return True

        # The worked example is the only payload guaranteed to satisfy every
        # documented rule, so it is the fixture — a hand-written stub would
        # drift from the schema the moment a field rule changes.
        payload = as_first_audit(d)
        payload_path = root / "payload.json"
        payload_path.write_text(json.dumps(payload))
        check("helper accepts the worked example as a first-audit payload",
              module.load_payload(payload_path, "canonical")["latest"]["audit_id"]
              == payload["latest"]["audit_id"])
        incomplete_path = root / "incomplete.json"
        incomplete_path.write_text(json.dumps({"schema_version": module.SCHEMA_VERSION}))
        try:
            module.load_payload(incomplete_path, "canonical")
            incomplete_rejected = False
        except ValueError:
            incomplete_rejected = True
        check("helper rejects an incomplete recovery/canonical payload",
              incomplete_rejected)

        # -- semantic validation (a payload that would corrupt a future run) --
        # Each of these was demonstrably persistable before the helper
        # validated semantics, on BOTH the canonical and recovery paths.
        def as_recovery(candidate):
            return as_first_audit(candidate)

        def _bool_score(p):
            """A boolean where an integer 1-5 belongs, with the total still balancing."""
            factors = p["latest"]["lift"]["factors"]
            for name in factors:
                factors[name]["score"] = 3
            factors["value_proposition"]["score"] = True  # reads as 1 in arithmetic
            p["latest"]["lift"]["total"] = 3 * 5 + 1
            p["latest"]["lift"]["lowest_two"] = ["value_proposition", "clarity"]

        def _duplicate_lowest_two(p):
            """The same factor named twice, with the bottom two forced into a tie."""
            factors = p["latest"]["lift"]["factors"]
            order = sorted(factors, key=lambda k: factors[k]["score"])
            factors[order[0]]["score"] = factors[order[1]]["score"] = 1
            p["latest"]["lift"]["total"] = sum(f["score"] for f in factors.values())
            p["latest"]["lift"]["lowest_two"] = [order[0], order[0]]

        def _non_public_host(p):
            """A single-label host (no dot) is not a public website."""
            p["page"].update(
                url="https://localhost/pricing",
                host="localhost",
                slug="localhost-pricing",
            )

        def _shopify_page(p, path="/example-app"):
            p["page"].update(
                url=f"https://apps.shopify.com{path}",
                host="apps.shopify.com",
                path=path,
                slug=module.derive_slug("apps.shopify.com", path),
                target="shopify_app_store",
            )

        def _null_page_identity(p):
            p["page"].update(
                url=None,
                host=None,
                path=None,
                slug=None,
                conversion_goal=None,
            )

        def _contradictory_outcome(p):
            experiment = p["experiments"][-1]
            experiment["status"] = "won"
            experiment["outcome"]["result"] = "loss"

        def _missing_terminal_outcome(p):
            experiment = p["experiments"][-1]
            experiment["status"] = "won"
            experiment["outcome"] = None

        def _duplicate_ranked_experiment(p):
            p["latest"]["pxl"]["ideas"][1]["experiment_id"] = (
                p["latest"]["pxl"]["ideas"][0]["experiment_id"])

        def _reverse_history(p):
            older = clone(p["history"][0])
            older.update(audit_id="2026-05-01", audited_at="2026-05-01")
            p["history"] = [older, p["history"][0]]

        def _duplicate_history_id(p):
            p["history"].append(clone(p["history"][0]))

        mutations = {
            "an invented experiment status":
                lambda p: p["experiments"][0].update(status="totally_made_up"),
            "an audit-set status the skill may never assign":
                lambda p: p["experiments"][0].update(status="won", status_source="audit"),
            "an outcome without a user_reported source":
                lambda p: p["experiments"][2].update(outcome={"result": "win"}),
            "an engineering issue missing its check_id":
                lambda p: p["engineering_issues"][0].pop("check_id"),
            "an issue resolved by a check that never ran":
                lambda p: (p["engineering_issues"][0].update(
                    status="fixed", resolved_in_audit=p["latest"]["audit_id"]),
                    p["latest"].update(engineering_checks_run=[])),
            "a PXL subtotal that disagrees with its criteria":
                lambda p: p["latest"]["pxl"]["ideas"][0]["criteria"]["ease"].update(subtotal=3),
            "an invented inner PXL criterion":
                lambda p: p["latest"]["pxl"]["ideas"][0]["criteria"]["potential"].update(
                    invented_criterion=True),
            "a LIFT total that disagrees with its factors":
                lambda p: p["latest"]["lift"].update(total=25),
            "a criterion stored as 0 instead of false/null":
                lambda p: p["latest"]["pxl"]["ideas"][0]["criteria"]["ease"].update(no_dev_time=0),
            "a priority tier assigned in heuristic-only mode":
                lambda p: p["latest"]["pxl"].update(scoring_mode="heuristic_only"),
            "a block with no observed_in provenance":
                lambda p: p["latest"]["lift"].pop("observed_in"),
            "a dangling blocks_experiments reference":
                lambda p: p["engineering_issues"][0].update(blocks_experiments=["exp-nope"]),
            # bool subclasses int and True == 1, so every plain isinstance/!=
            # integer test accepted a boolean and let it reach disk as JSON
            # `true` with the arithmetic still balancing — the same collapse the
            # criteria identity test prevents, in the fields it never covered.
            "a LIFT factor score stored as boolean true":
                lambda p: _bool_score(p),
            "sections_emitted containing a boolean":
                lambda p: p["latest"].update(scope="focused", sections_emitted=[True, 2]),
            # The slug IS the filename, and the slug rule is deterministic.
            "a slug that disagrees with its own host and path":
                lambda p: p["page"].update(slug="not-the-derived-slug"),
            "a host that is not the host of page.url":
                lambda p: p["page"].update(host="evil.example.com"),
            "null page identity fields":
                lambda p: _null_page_identity(p),
            "a non-absolute page URL":
                lambda p: p["page"].update(url="/pricing"),
            # target selects the GA4 scoping regime in SKILL.md Step 2.
            "an app-store target on a website host":
                lambda p: p["page"].update(target="shopify_app_store"),
            "a Shopify App Store path that is not an app listing":
                lambda p: _shopify_page(p, "/partners/directory"),
            "GSC marked available for the Shopify App Store listing":
                lambda p: (_shopify_page(p),
                           p["latest"]["data_layers"]["gsc"].update(
                               available=True, source="gsc skill", note=None)),
            "a data layer missing source and note":
                lambda p: (p["latest"]["data_layers"]["ga4"].pop("source"),
                           p["latest"]["data_layers"]["ga4"].pop("note")),
            "latest.audited_at unrelated to audit_id":
                lambda p: p["latest"].update(audited_at="not-a-date"),
            "an impossible latest audit date":
                lambda p: p["latest"].update(audit_id="2026-99-99"),
            "a same-day audit suffix below -2":
                lambda p: p["latest"].update(audit_id="2026-07-23-1"),
            "a date_range whose start is after its end":
                lambda p: p["latest"]["date_range"].update(
                    start="2026-12-31", end="2026-01-01"),
            "a won experiment carrying a loss outcome":
                lambda p: _contradictory_outcome(p),
            "a terminal experiment missing its outcome":
                lambda p: _missing_terminal_outcome(p),
            # Comparing sets of scores could not see a duplicated name: with the
            # bottom two tied, [X, X] collapsed to the same one-element set as
            # the correct answer.
            "lowest_two naming the same factor twice":
                lambda p: _duplicate_lowest_two(p),
            "history.measured storing integer 1 instead of true":
                lambda p: p["history"][0]["measured"].update(lift=1),
            "history.measured storing integer 0 instead of false":
                lambda p: p["history"][0]["measured"].update(metrics=0),
            "a malformed history audit id":
                lambda p: p["history"][0].update(audit_id="not-a-date"),
            "history snapshots not ordered newest first":
                lambda p: _reverse_history(p),
            "duplicate history audit ids":
                lambda p: _duplicate_history_id(p),
            "latest.audit_id duplicated in history":
                lambda p: p["history"][0].update(
                    audit_id=p["latest"]["audit_id"],
                    audited_at=p["latest"]["audited_at"]),
            "an empty changes_since_previous on a re-audit":
                lambda p: p["latest"].update(changes_since_previous={}),
            "a fabricated metric delta":
                lambda p: p["latest"]["changes_since_previous"]["metric_deltas"].update(
                    conversion_rate_overall=0.9),
            "a compared_against audit absent from history":
                lambda p: p["latest"]["changes_since_previous"]["compared_against"].update(
                    metrics="2019-01-01"),
            "an issue resolution stamped with a non-audit token":
                lambda p: p["engineering_issues"][1].update(
                    resolved_in_audit="banana"),
            "duplicate PXL ranks":
                lambda p: p["latest"]["pxl"]["ideas"][1].update(
                    rank=p["latest"]["pxl"]["ideas"][0]["rank"]),
            "non-contiguous PXL ranks":
                lambda p: p["latest"]["pxl"]["ideas"][1].update(rank=7),
            "a duplicate experiment in the current PXL ranking":
                lambda p: _duplicate_ranked_experiment(p),
            "a host that is not a public domain name":
                lambda p: _non_public_host(p),
        }
        canonical_only = {
            "history.measured storing integer 1 instead of true",
            "history.measured storing integer 0 instead of false",
            "a malformed history audit id",
            "history snapshots not ordered newest first",
            "duplicate history audit ids",
            "latest.audit_id duplicated in history",
            "an empty changes_since_previous on a re-audit",
            "a fabricated metric delta",
            "a compared_against audit absent from history",
        }
        for label, mutate in mutations.items():
            candidate = clone(d)
            mutate(candidate)
            check(f"helper rejects {label}", rejected(candidate))
            if label not in canonical_only:
                recovery_candidate = as_first_audit(d)
                mutate(recovery_candidate)
                check(f"...and rejects it on the recovery path too",
                      rejected(recovery_candidate, "recovery"))

        # The skill audits any public website, not one company's hosts. A
        # host allow-list creeping back in would silently refuse every other
        # site's profile, so acceptance is checked, not just rejection.
        for any_host in ("shop.example.org", "www.another-store.co.uk"):
            accepted = clone(d)
            accepted["page"].update(
                url=f"https://{any_host}/pricing",
                host=any_host,
                slug=module.derive_slug(any_host, "/pricing"),
            )
            check(f"helper accepts an arbitrary public website ({any_host})",
                  not rejected(accepted))

        check("helper rejects a payload at an unsupported schema_version",
              rejected({**clone(d), "schema_version": "0.9"}))
        check("recovery payload may not claim inherited history",
              rejected(clone(d), "recovery"))

        # -- engineering_checks_run must be rebuilt every run, not carried --
        # The four measured blocks self-identify as stale via observed_in;
        # this list needs its own stamp or a focused slice can inherit a prior
        # run's evidence and resolve an issue nobody re-tested.
        focused = clone(d)
        focused["latest"].update(audit_id="2026-08-04", audited_at="2026-08-04",
                                 scope="focused", sections_emitted=[4])
        focused["latest"]["lift"]["observed_in"] = "2026-08-04"
        focused["latest"]["changes_since_previous"].update(
            compared_against={"metrics": None, "lift": "2026-06-12", "pxl": None},
            not_compared=[
                "metrics not measured this run — focused LIFT slice",
                "pxl not measured this run — focused LIFT slice",
            ],
            metric_deltas={},
            new_experiments=[],
            recurring_experiments=[],
            dropped_experiments=[],
            rank_changes={},
            new_issues=[],
            resolved_issues=[],
        )
        check("focused run carrying forward engineering_checks_run is rejected",
              rejected(focused))
        focused["latest"]["engineering_checks_run"] = []
        focused["latest"]["engineering_checks_run_observed_in"] = "2026-08-04"
        check("...and is accepted once the list is rebuilt and stamped this run",
              not rejected(focused))
        bad_focused_deltas = clone(focused)
        bad_focused_deltas["latest"]["changes_since_previous"].update(
            compared_against={
                "metrics": "2019-01-01",
                "lift": "2026-06-12",
                "pxl": None,
            },
            not_compared=[],
            metric_deltas={"conversion_rate_overall": 0.9},
        )
        check("focused run cannot persist deltas for a carried metrics block",
              rejected(bad_focused_deltas))
        focused["engineering_issues"][1].update(status="fixed", resolved_in_audit="2026-08-04")
        check("...but still cannot resolve an issue whose check did not run",
              rejected(focused))

        # -- comparable is a guard, not an unchecked narration ---------------
        mode_mismatch = clone(d)
        mode_mismatch["latest"]["pxl"]["scoring_mode"] = "full_data"
        check("helper rejects comparable=true across PXL scoring modes",
              rejected(mode_mismatch))
        mode_mismatch["latest"]["changes_since_previous"].update(
            comparable=False,
            comparability_note="PXL scoring mode changed from partial_data to full_data.",
        )
        check("...and accepts the mismatch when marked non-comparable",
              not rejected(mode_mismatch))

        window_mismatch = clone(d)
        window_mismatch["latest"]["date_range"]["start"] = "2026-05-01"
        check("helper rejects comparable=true across metric window lengths",
              rejected(window_mismatch))

        layer_mismatch = clone(d)
        layer_mismatch["latest"]["data_layers"]["ga4"]["available"] = False
        check("helper rejects comparable=true when a delta's data layer changed",
              rejected(layer_mismatch))

        blank_note = clone(mode_mismatch)
        blank_note["latest"]["changes_since_previous"]["comparability_note"] = " "
        check("helper requires a reason when comparable=false",
              rejected(blank_note))

        # -- the payload must be bound to the file it is written into --------
        # A profile filed under another page's slug overwrites that page's
        # history and exits 0; the fingerprint guard cannot catch it, being
        # MISSING on a first write and a correct match for the victim on a
        # second. Both write primitives enforce it, not just the CLI, so an
        # importer cannot route around it.
        wrong_file = root / "profiles" / "www-example-com-home.json"
        for label, writer in (
            ("canonical", lambda: module.atomic_canonical_write(
                wrong_file, payload, module.MISSING)),
            ("recovery", lambda: module.atomic_recovery_write(
                wrong_file, payload, "corrupt")),
        ):
            try:
                writer()
                misfiled = False
            except module.ProfileInvalidError:
                misfiled = True
            check(f"{label} write refuses a payload filed under another page's slug",
                  misfiled)
        check("...and no file was created for the wrong page",
              not any(root.joinpath("profiles").glob("www-example-com-home*")))

        identityless = clone(payload)
        _null_page_identity(identityless)
        arbitrary_file = root / "profiles" / "unrelated-page.json"
        try:
            module.atomic_canonical_write(
                arbitrary_file, identityless, module.MISSING)
            identity_bypass_rejected = False
        except module.ProfileInvalidError:
            identity_bypass_rejected = True
        check("non-string page identity cannot bypass filename binding",
              identity_bypass_rejected)
        check("...and the arbitrary profile filename was not created",
              not arbitrary_file.exists())

        # Validation belongs in the primitives too: callers importing this
        # module must not be able to bypass the CLI's load_payload().
        invalid_direct = clone(payload)
        invalid_direct["experiments"][0]["status"] = "totally_made_up"
        for label, writer in (
            ("canonical", lambda: module.atomic_canonical_write(
                canonical, invalid_direct, module.MISSING)),
            ("recovery", lambda: module.atomic_recovery_write(
                canonical, as_recovery(invalid_direct), "corrupt")),
        ):
            try:
                writer()
                direct_rejected = False
            except module.ProfileInvalidError:
                direct_rejected = True
            check(f"{label} primitive validates semantics without the CLI",
                  direct_rejected)
        check("invalid direct calls create no profile files",
              not canonical.exists()
              and not any(module.PROFILE_DIR.glob(f"{canonical.stem}.*.json")))

        outside = root / "elsewhere" / canonical.name
        try:
            module.atomic_canonical_write(outside, payload, module.MISSING)
            outside_rejected = False
        except module.ProfileInvalidError:
            outside_rejected = True
        check("canonical writes are bound to this skill's profiles directory",
              outside_rejected)
        check("...and an outside-directory attempt creates nothing",
              not outside.exists())

        # The slug rule is the filename rule, so the implementation must agree
        # with every row of the table the schema documents.
        for url, expected_slug in (
            ("https://www.example.com/pricing", "www-example-com-pricing"),
            ("https://www.example.com/", "www-example-com-home"),
            ("https://app.example.com/features", "app-example-com-features"),
            ("https://apps.shopify.com/example-app", "apps-shopify-com-example-app"),
        ):
            parts = urlsplit(url)
            check(f"derive_slug matches the documented table for {url}",
                  module.derive_slug(parts.netloc, parts.path) == expected_slug,
                  f"got {module.derive_slug(parts.netloc, parts.path)!r}")
            check(f"...and the schema table still documents {expected_slug}",
                  expected_slug in schema_src)

        empty_metrics = clone(payload)
        empty_metrics["latest"]["metrics"] = {
            "observed_in": empty_metrics["latest"]["audit_id"],
            "ga4": {"note": "no numeric leaves"},
            "gsc": None,
            "session_replay": None,
        }
        check("helper rejects measured metrics that cannot produce a compact baseline",
              rejected(empty_metrics))
        check("...and rejects uncompactable metrics on the recovery path too",
              rejected(as_recovery(empty_metrics), "recovery"))

        for token, value in (
            ("NaN", float("nan")),
            ("Infinity", float("inf")),
            ("-Infinity", float("-inf")),
        ):
            nonfinite = clone(payload)
            nonfinite["latest"]["metrics"]["ga4"]["sessions"] = value
            check(f"helper rejects non-finite metric {token}",
                  rejected(nonfinite))
            check(f"...and rejects {token} on the recovery path too",
                  rejected(as_recovery(nonfinite), "recovery"))

        malformed_url = clone(payload)
        malformed_url["page"]["url"] = "https://[bad"
        try:
            module.validate_profile(malformed_url, "canonical")
            malformed_url_result = "accepted"
        except module.ProfileInvalidError:
            malformed_url_result = "invalid"
        except Exception as exc:  # noqa: BLE001 - raw ValueError is the defect
            malformed_url_result = type(exc).__name__
        check("malformed page URLs become ProfileInvalidError",
              malformed_url_result == "invalid", malformed_url_result)

        malformed_shapes = []
        for mutate in (
            lambda p: p.update(experiments=None),
            lambda p: p.update(engineering_issues=0),
            lambda p: p["experiments"][0].update(id={}),
            lambda p: p["engineering_issues"][0].update(id=[]),
            lambda p: p["latest"]["lift"]["lowest_two"].__setitem__(0, {}),
            lambda p: p["history"][0]["lift"]["factors"].update(clarity="bad"),
        ):
            malformed = clone(d)
            mutate(malformed)
            try:
                module.validate_profile(malformed, "canonical")
                malformed_shapes.append("accepted")
            except module.ProfileInvalidError:
                malformed_shapes.append("invalid")
            except Exception as exc:  # noqa: BLE001 - raw exceptions are the defect
                malformed_shapes.append(type(exc).__name__)
        check("malformed JSON shapes always become ProfileInvalidError",
              malformed_shapes == ["invalid"] * len(malformed_shapes),
              str(malformed_shapes))

        malformed_cli = clone(d)
        malformed_cli["history"][0]["lift"]["factors"]["clarity"] = "bad"
        malformed_path = root / "malformed-profile.json"
        malformed_path.write_text(json.dumps(malformed_cli))
        malformed_result = subprocess.run(
            [
                sys.executable,
                str(PROFILE_STORE),
                "validate",
                "--payload",
                str(malformed_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        check("malformed CLI validation exits INVALID without a traceback",
              malformed_result.returncode == 2
              and malformed_result.stderr.startswith("INVALID:")
              and "Traceback" not in malformed_result.stderr,
              malformed_result.stderr[:200])

        nonfinite_path = root / "nonfinite-profile.json"
        nonfinite_cli = clone(payload)
        nonfinite_cli["latest"]["metrics"]["ga4"]["sessions"] = float("inf")
        nonfinite_path.write_text(json.dumps(nonfinite_cli))
        nonfinite_result = subprocess.run(
            [
                sys.executable,
                str(PROFILE_STORE),
                "validate",
                "--payload",
                str(nonfinite_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        check("non-finite CLI validation exits INVALID before the write lock",
              nonfinite_result.returncode == 2
              and nonfinite_result.stderr.startswith("INVALID:")
              and "Infinity" in nonfinite_result.stderr
              and "Traceback" not in nonfinite_result.stderr,
              nonfinite_result.stderr[:200])

        check("missing canonical fingerprints as MISSING",
              module.fingerprint(canonical) == module.MISSING)

        fabricated_first = clone(d)
        try:
            module.atomic_canonical_write(
                canonical, fabricated_first, module.MISSING)
            fabricated_first_rejected = False
        except module.ProfileInvalidError:
            fabricated_first_rejected = True
        check("a missing canonical cannot seed fabricated history or deltas",
              fabricated_first_rejected)
        check("...and rejected first-write history creates no canonical file",
              not canonical.exists())

        born_fixed = clone(payload)
        born_fixed_issue = born_fixed["engineering_issues"][0]
        born_fixed_issue.update(
            status="fixed",
            resolved_in_audit=born_fixed["latest"]["audit_id"],
        )
        check("first canonical profile cannot create an issue already fixed",
              rejected(born_fixed, "recovery"))
        try:
            module.atomic_canonical_write(
                canonical, born_fixed, module.MISSING)
            born_fixed_rejected = False
        except module.ProfileInvalidError:
            born_fixed_rejected = True
        check("atomic first write rejects an issue born fixed",
              born_fixed_rejected)
        check("...and creates no canonical file for the false resolution",
              not canonical.exists())

        future_first = clone(payload)
        future_id = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        future_first["latest"].update(
            audit_id=future_id,
            audited_at=future_id,
            engineering_checks_run_observed_in=future_id,
        )
        for block in module.BLOCKS:
            value = future_first["latest"].get(block)
            if isinstance(value, dict):
                value["observed_in"] = future_id
        for experiment in future_first["experiments"]:
            experiment["created_in_audit"] = future_id
            experiment["last_seen_in_audit"] = future_id
        for issue in future_first["engineering_issues"]:
            issue["first_seen"] = future_id
            issue["last_seen"] = future_id
            if issue["status"] == "fixed":
                issue["resolved_in_audit"] = future_id
        module.validate_profile(future_first, "canonical")
        try:
            module.atomic_canonical_write(
                canonical, future_first, module.MISSING)
            future_first_rejected = False
        except module.ProfileInvalidError:
            future_first_rejected = True
        check("actual writes reject a future latest.audit_id",
              future_first_rejected)
        check("...and a rejected future audit creates no canonical file",
              not canonical.exists())

        payload["latest"]["metrics"]["ga4"]["demo_cta_clicks"] = 0
        module.atomic_canonical_write(canonical, payload, module.MISSING)
        original_bytes = canonical.read_bytes()
        base_audit_id = payload["latest"]["audit_id"]
        check("first canonical write succeeds atomically",
              json.loads(original_bytes)["latest"]["audit_id"] == base_audit_id)
        try:
            module.atomic_canonical_write(canonical, payload, module.MISSING)
            conflict_raised = False
        except module.ProfileConflictError:
            conflict_raised = True
        check("stale fingerprint is rejected", conflict_raised)
        check("conflict leaves canonical bytes unchanged",
              canonical.read_bytes() == original_bytes)

        # A real re-audit must authenticate the complete compact demotion, not
        # merely reuse the canonical audit id. Otherwise a draft can rewrite
        # the source and make any internally consistent fabricated delta pass.
        valid_reaudit = make_reaudit(payload)
        module.validate_profile(valid_reaudit, "canonical")
        source_rewrite = clone(valid_reaudit)
        source_rewrite["history"][0]["lift"]["total"] -= 2
        source_rewrite["history"][0]["lift"]["factors"]["value_proposition"] -= 2
        source_rewrite["latest"]["changes_since_previous"]["lift_total_delta"] = 2
        source_rewrite["latest"]["changes_since_previous"]["lift_deltas"][
            "value_proposition"] = 2
        module.validate_profile(source_rewrite, "canonical")
        try:
            module.validate_transition(payload, source_rewrite)
            source_rewrite_rejected = False
        except module.ProfileInvalidError:
            source_rewrite_rejected = True
        check("locked transition rejects a rewritten comparison source",
              source_rewrite_rejected)
        before_source_probe = canonical.read_bytes()
        try:
            module.atomic_canonical_write(
                canonical,
                source_rewrite,
                module.fingerprint(canonical),
            )
            atomic_source_rejected = False
        except module.ProfileInvalidError:
            atomic_source_rejected = True
        check("atomic write rejects source tampering end to end",
              atomic_source_rejected)
        check("...and source tampering leaves canonical bytes untouched",
              canonical.read_bytes() == before_source_probe)

        metric_memory_drop = clone(valid_reaudit)
        metric_memory_drop["history"][0]["key_metrics"] = {}
        try:
            module.validate_profile(metric_memory_drop, "canonical")
            module.validate_transition(payload, metric_memory_drop)
            metric_memory_drop_rejected = False
        except module.ProfileInvalidError:
            metric_memory_drop_rejected = True
        check("profile write rejects an empty measured key_metrics baseline",
              metric_memory_drop_rejected)
        expected_metric_names = module._Validator.key_metric_names(
            payload["latest"]["metrics"])
        check("deterministic compact history retains every unambiguous numeric metric",
              set(valid_reaudit["history"][0]["key_metrics"]) == set(expected_metric_names)
              and bool(expected_metric_names))

        prior_collision = clone(payload)
        prior_collision["page"].update(
            url="https://www.example.com/a-b",
            path="/a-b",
            slug="www-example-com-a-b",
        )
        collision_transition = make_reaudit(prior_collision)
        collision_transition["page"].update(
            url="https://www.example.com/a/b",
            path="/a/b",
            slug="www-example-com-a-b",
        )
        module.validate_profile(collision_transition, "canonical")
        try:
            module.validate_transition(prior_collision, collision_transition)
            slug_collision_rejected = False
        except module.ProfileInvalidError:
            slug_collision_rejected = True
        check("a slug collision cannot merge two distinct page paths",
              slug_collision_rejected)

        # The retained tail is authenticated too; a re-audit may trim only the
        # oldest entry when the 12-snapshot cap requires it.
        prior_with_tail = clone(d)
        tail_drop = make_reaudit(prior_with_tail)
        tail_drop["history"] = tail_drop["history"][:1]
        module.validate_profile(tail_drop, "canonical")
        try:
            module.validate_transition(prior_with_tail, tail_drop)
            tail_drop_rejected = False
        except module.ProfileInvalidError:
            tail_drop_rejected = True
        check("locked transition rejects deletion of retained history",
              tail_drop_rejected)

        # Longitudinal records survive even when they are absent from this run's
        # ranking/check results.
        prior_with_memory = clone(payload)
        settled = clone(d["experiments"][-1])
        settled.update(
            id="exp-memory-only-winner",
            name="Memory-only winner",
            created_in_audit=payload["latest"]["audit_id"],
            last_seen_in_audit=payload["latest"]["audit_id"],
        )
        open_issue = clone(d["engineering_issues"][0])
        open_issue.update(
            id="eng-memory-only-open",
            first_seen=payload["latest"]["audit_id"],
            last_seen=payload["latest"]["audit_id"],
            status="open",
            resolved_in_audit=None,
            blocks_experiments=[],
        )
        prior_with_memory["experiments"].append(settled)
        prior_with_memory["engineering_issues"].append(open_issue)
        memory_drop = make_reaudit(prior_with_memory)
        memory_drop["experiments"] = [
            experiment for experiment in memory_drop["experiments"]
            if experiment["id"] != settled["id"]
        ]
        memory_drop["engineering_issues"] = [
            issue for issue in memory_drop["engineering_issues"]
            if issue["id"] != open_issue["id"]
        ]
        module.validate_profile(memory_drop, "canonical")
        try:
            module.validate_transition(prior_with_memory, memory_drop)
            memory_drop_rejected = False
        except module.ProfileInvalidError:
            memory_drop_rejected = True
        check("locked transition rejects deleted longitudinal records",
              memory_drop_rejected)

        # Resolution is authorized by the canonical issue's stable check token,
        # never by a replacement token that merely happens to be in this run.
        prior_open = clone(payload)
        issue_id = "eng-missing-scroll-events"
        prior_issue = next(
            issue for issue in prior_open["engineering_issues"]
            if issue["id"] == issue_id
        )
        prior_issue.update(status="open", resolved_in_audit=None)
        valid_resolution = make_reaudit(prior_open)
        resolved_issue = next(
            issue for issue in valid_resolution["engineering_issues"]
            if issue["id"] == issue_id
        )
        resolved_issue.update(
            status="fixed",
            resolved_in_audit=valid_resolution["latest"]["audit_id"],
        )
        valid_resolution["latest"]["changes_since_previous"]["resolved_issues"] = [
            issue_id]
        module.validate_profile(valid_resolution, "canonical")
        try:
            module.validate_transition(prior_open, valid_resolution)
            valid_resolution_accepted = True
        except module.ProfileInvalidError:
            valid_resolution_accepted = False
        check("stable prior check_id still permits a proven open -> fixed transition",
              valid_resolution_accepted)

        valid_redetection = make_reaudit(prior_open)
        redetected_issue = next(
            issue for issue in valid_redetection["engineering_issues"]
            if issue["id"] == issue_id
        )
        redetected_issue["last_seen"] = valid_redetection["latest"]["audit_id"]
        module.validate_profile(valid_redetection, "canonical")
        try:
            module.validate_transition(prior_open, valid_redetection)
            valid_redetection_accepted = True
        except module.ProfileInvalidError:
            valid_redetection_accepted = False
        check("stable prior check_id still permits a proven open re-detection",
              valid_redetection_accepted)

        check_id_swap = make_reaudit(prior_open)
        current_issue = next(
            issue for issue in check_id_swap["engineering_issues"]
            if issue["id"] == issue_id
        )
        current_issue.update(
            status="fixed",
            resolved_in_audit=check_id_swap["latest"]["audit_id"],
            check_id="session_replay_hero_cta_error_clicks",
        )
        check_id_swap["latest"]["changes_since_previous"]["resolved_issues"] = [issue_id]
        module.validate_profile(check_id_swap, "canonical")
        try:
            module.validate_transition(prior_open, check_id_swap)
            check_id_swap_rejected = False
        except module.ProfileInvalidError:
            check_id_swap_rejected = True
        check("locked transition rejects a swapped issue check_id",
              check_id_swap_rejected)

        bypassed_resolution = make_reaudit(prior_open)
        bypassed_issue = next(
            issue for issue in bypassed_resolution["engineering_issues"]
            if issue["id"] == issue_id
        )
        bypassed_issue.update(status="fixed", resolved_in_audit="2026-06-12")
        bypassed_resolution["latest"]["engineering_checks_run"] = [
            check_id for check_id in bypassed_resolution["latest"]["engineering_checks_run"]
            if check_id != bypassed_issue["check_id"]
        ]
        module.validate_profile(bypassed_resolution, "canonical")
        try:
            module.validate_transition(prior_open, bypassed_resolution)
            transition_rejected = False
        except module.ProfileInvalidError:
            transition_rejected = True
        check("open -> fixed cannot hide behind a prior resolved_in_audit stamp",
              transition_rejected)

        # Schema 1.0 did not carry issue check ids. Migration may assign the
        # stable token, but cannot use that newly assigned token to infer a fix.
        legacy = clone(payload)
        legacy["schema_version"] = "1.0"
        legacy["latest"].pop("engineering_checks_run")
        legacy["latest"].pop("engineering_checks_run_observed_in")
        legacy["engineering_issues"] = [clone(d["engineering_issues"][0])]
        legacy["engineering_issues"][0].update(
            first_seen=legacy["latest"]["audit_id"],
            last_seen=legacy["latest"]["audit_id"],
            status="open",
            resolved_in_audit=None,
        )
        legacy["engineering_issues"][0].pop("check_id")
        migration = make_reaudit(legacy)
        migration["schema_version"] = module.SCHEMA_VERSION
        migration["latest"]["engineering_checks_run"] = []
        migration["engineering_issues"][0]["check_id"] = (
            "session_replay_hero_cta_error_clicks")
        module.validate_profile(migration, "canonical")
        try:
            module.validate_transition(legacy, migration)
            migration_accepted = True
        except module.ProfileInvalidError:
            migration_accepted = False
        check("1.0 migration may assign a stable check_id while keeping issue open",
              migration_accepted)
        try:
            module.validate_legacy_profile(legacy)
            legacy_shape_accepted = True
        except module.ProfileInvalidError:
            legacy_shape_accepted = False
        check("the documented 1.0 shape passes dedicated legacy validation",
              legacy_shape_accepted)
        invalid_migration = clone(migration)
        invalid_migration["engineering_issues"][0].update(
            status="fixed",
            resolved_in_audit=invalid_migration["latest"]["audit_id"],
        )
        invalid_migration["latest"]["engineering_checks_run"] = [
            invalid_migration["engineering_issues"][0]["check_id"]
        ]
        invalid_migration["latest"]["changes_since_previous"]["resolved_issues"] = [
            invalid_migration["engineering_issues"][0]["id"]
        ]
        module.validate_profile(invalid_migration, "canonical")
        try:
            module.validate_transition(legacy, invalid_migration)
            legacy_fix_rejected = False
        except module.ProfileInvalidError:
            legacy_fix_rejected = True
        check("1.0 migration cannot infer a fix from a newly assigned check_id",
              legacy_fix_rejected)

        focused_transition = make_reaudit(payload)
        focused_transition["latest"].update(
            scope="focused",
            sections_emitted=[4],
            date_range=None,
            engineering_checks_run=[],
        )
        for block in ("page_snapshot", "metrics", "pxl"):
            focused_transition["latest"][block]["observed_in"] = (
                payload["latest"]["audit_id"])
        focused_transition["latest"]["changes_since_previous"].update(
            compared_against={
                "metrics": None,
                "lift": payload["latest"]["audit_id"],
                "pxl": None,
            },
            not_compared=[
                "metrics not measured this run — focused LIFT slice",
                "pxl not measured this run — focused LIFT slice",
            ],
            metric_deltas={},
            new_experiments=[],
            recurring_experiments=[],
            dropped_experiments=[],
            rank_changes={},
        )
        carried_ids = {
            idea["experiment_id"]
            for idea in focused_transition["latest"]["pxl"]["ideas"]
        }
        for current_experiment in focused_transition["experiments"]:
            if current_experiment["id"] in carried_ids:
                prior_experiment = next(
                    experiment for experiment in payload["experiments"]
                    if experiment["id"] == current_experiment["id"]
                )
                current_experiment["last_seen_in_audit"] = (
                    prior_experiment["last_seen_in_audit"])
        module.validate_profile(focused_transition, "canonical")
        try:
            module.validate_transition(payload, focused_transition)
            focused_transition_accepted = True
        except module.ProfileInvalidError:
            focused_transition_accepted = False
        check("continuity checks preserve a valid focused LIFT-only transition",
              focused_transition_accepted)

        lift_carried = clone(focused_transition)
        new_id = lift_carried["latest"]["audit_id"]
        lift_carried["latest"].update(
            scope="focused",
            sections_emitted=[2],
        )
        lift_carried["latest"]["lift"] = clone(payload["latest"]["lift"])
        lift_carried["latest"]["metrics"] = clone(payload["latest"]["metrics"])
        lift_carried["latest"]["metrics"]["observed_in"] = new_id
        lift_carried["latest"]["changes_since_previous"].update(
            compared_against={
                "metrics": payload["latest"]["audit_id"],
                "lift": None,
                "pxl": None,
            },
            not_compared=[
                "lift not measured this run — focused metrics slice",
                "pxl not measured this run — focused metrics slice",
            ],
            lift_total_delta=None,
            lift_deltas={},
            metric_deltas={},
        )
        module.validate_profile(lift_carried, "canonical")
        module.validate_transition(payload, lift_carried)

        carried_candidates = {
            "page_snapshot": focused_transition,
            "metrics": focused_transition,
            "lift": lift_carried,
            "pxl": focused_transition,
        }
        for block, valid_candidate in carried_candidates.items():
            changed = clone(valid_candidate)
            if block == "page_snapshot":
                changed["latest"][block]["headline"] += " — rewritten"
            elif block == "metrics":
                changed["latest"][block]["ga4"]["sessions"] += 999999
            elif block == "lift":
                changed["latest"][block]["factors"]["clarity"]["evidence"] += " Rewritten."
            else:
                changed["latest"][block]["ideas"][0]["name"] += " — rewritten"
            module.validate_profile(changed, "canonical")
            try:
                module.validate_transition(payload, changed)
                changed_rejected = False
            except module.ProfileInvalidError:
                changed_rejected = True
            check(f"locked transition rejects mutation of carried {block}",
                  changed_rejected)

            deleted = clone(valid_candidate)
            deleted["latest"][block] = None
            module.validate_profile(deleted, "canonical")
            try:
                module.validate_transition(payload, deleted)
                deleted_rejected = False
            except module.ProfileInvalidError:
                deleted_rejected = True
            check(f"locked transition rejects deletion of carried {block}",
                  deleted_rejected)

        for label, mutate in (
            (
                "integer-to-boolean",
                lambda p: p["latest"]["metrics"]["ga4"].update(
                    demo_cta_clicks=False),
            ),
            (
                "integer-to-float",
                lambda p: p["latest"]["metrics"]["ga4"].update(
                    sessions=float(
                        p["latest"]["metrics"]["ga4"]["sessions"])),
            ),
        ):
            cross_type = clone(focused_transition)
            mutate(cross_type)
            module.validate_profile(cross_type, "canonical")
            try:
                module.validate_transition(payload, cross_type)
                cross_type_rejected = False
            except module.ProfileInvalidError:
                cross_type_rejected = True
            check(f"locked transition rejects carried {label} rewrites",
                  cross_type_rejected)

        atomic_carried_mutation = clone(focused_transition)
        atomic_carried_mutation["latest"]["metrics"]["ga4"][
            "demo_cta_clicks"] = False
        before_carried_probe = canonical.read_bytes()
        try:
            module.atomic_canonical_write(
                canonical,
                atomic_carried_mutation,
                module.fingerprint(canonical),
            )
            atomic_carried_rejected = False
        except module.ProfileInvalidError:
            atomic_carried_rejected = True
        check("atomic write rejects carried-block tampering end to end",
              atomic_carried_rejected)
        check("...and carried-block tampering leaves canonical bytes untouched",
              canonical.read_bytes() == before_carried_probe)

        module.atomic_canonical_write(
            canonical,
            valid_reaudit,
            module.fingerprint(canonical),
        )
        check("matching fingerprint permits a valid atomic re-audit",
              json.loads(canonical.read_text())["latest"]["audit_id"]
              == valid_reaudit["latest"]["audit_id"])

        # Two valid first writers racing from MISSING: exactly one creates the
        # canonical file and the other sees the changed fingerprint.
        original_profile_dir = module.PROFILE_DIR
        module.PROFILE_DIR = root / "race" / "profiles"
        race_canonical = module.PROFILE_DIR / f"{d['page']['slug']}.json"
        race_payloads = [clone(payload), clone(payload)]

        def competing_write(candidate):
            try:
                module.atomic_canonical_write(
                    race_canonical, candidate, module.MISSING)
                return "written"
            except module.ProfileConflictError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            race_results = list(executor.map(competing_write, race_payloads))
        check("concurrent canonical updates cannot silently overwrite each other",
              sorted(race_results) == ["conflict", "written"])
        module.PROFILE_DIR = original_profile_dir

        # -- version guard: a fingerprint match is not permission to downgrade --
        # The canonical version is re-read under the write lock, never taken
        # from the audit's earlier read.
        newer = clone(payload)
        newer["schema_version"] = "999.0"
        canonical.write_text(json.dumps(newer))
        newer_bytes = canonical.read_bytes()
        try:
            module.atomic_canonical_write(canonical, payload, module.fingerprint(canonical))
            downgrade_blocked = False
        except module.ProfileVersionError:
            downgrade_blocked = True
        check("a newer-schema canonical cannot be replaced by this writer", downgrade_blocked)
        check("...and its bytes are untouched", canonical.read_bytes() == newer_bytes)

        canonical.write_bytes(b'{"half written')
        unparseable_bytes = canonical.read_bytes()
        try:
            module.atomic_canonical_write(canonical, payload, module.fingerprint(canonical))
            corrupt_blocked = False
        except module.ProfileVersionError:
            corrupt_blocked = True
        check("an unparseable canonical is routed to recovery, not overwritten", corrupt_blocked)
        check("...and its bytes are untouched", canonical.read_bytes() == unparseable_bytes)

        unknown_legacy = {
            "schema_version": "0.0",
            "valuable_legacy_history": ["only copy"],
        }
        canonical.write_text(json.dumps(unknown_legacy))
        unknown_legacy_bytes = canonical.read_bytes()
        try:
            module.assert_replaceable(canonical)
            unknown_legacy_blocked = False
        except module.ProfileVersionError:
            unknown_legacy_blocked = True
        check("an unknown older schema is preserved instead of assumed migratable",
              unknown_legacy_blocked)
        check("...and unknown legacy bytes are untouched",
              canonical.read_bytes() == unknown_legacy_bytes)

        malformed_legacy = {"schema_version": "1.0"}
        canonical.write_text(json.dumps(malformed_legacy))
        malformed_legacy_bytes = canonical.read_bytes()
        try:
            module.assert_replaceable(canonical)
            malformed_legacy_blocked = False
        except module.ProfileVersionError:
            malformed_legacy_blocked = True
        check("a malformed 1.0 canonical fails dedicated legacy validation",
              malformed_legacy_blocked)
        check("...and malformed legacy bytes are untouched",
              canonical.read_bytes() == malformed_legacy_bytes)

        corrupt_bytes = b'{"truncated":'
        canonical.write_bytes(corrupt_bytes)
        fixed_time = datetime.datetime(2026, 7, 27, 12, 34, 56)
        recovery_one = module.atomic_recovery_write(canonical, payload, "corrupt", fixed_time)
        recovery_two = module.atomic_recovery_write(canonical, payload, "corrupt", fixed_time)
        # Derived from the canonical stem, not hardcoded — the recovery file
        # must stay tied to the page whose profile it is preserving.
        stem = canonical.stem
        check("first recovery uses the timestamped name",
              recovery_one.name == f"{stem}.corrupt-20260727-123456.json")
        check("same-second recovery uses the numeric suffix",
              recovery_two.name == f"{stem}.corrupt-20260727-123456-2.json")
        with ThreadPoolExecutor(max_workers=6) as executor:
            concurrent_paths = list(executor.map(
                lambda _: module.atomic_recovery_write(canonical, payload, "corrupt", fixed_time),
                range(6),
            ))
        check("concurrent same-second recoveries all get unique files",
              len(set(concurrent_paths)) == 6
              and all(path.exists() for path in concurrent_paths))
        check("recovery writes preserve canonical bytes",
              canonical.read_bytes() == corrupt_bytes)

    print("\n== enum contract ==")
    # Closed-enum values in the worked example must be in their documented sets.
    # `engineering_issues[].source` is an OPEN set by design — only shape-checked.
    ENUMS = {
        "page.target": {"website", "shopify_app_store"},
        "page.goal_source": {"inferred_from_page", "inferred_from_audience_context", "user_specified"},
        "scope": {"full", "focused"},
        "capture_method": {"screenshot_desktop_and_mobile", "screenshot_desktop_only",
                           "screenshot_mobile_only", "text_fetch"},
        "status_source": {"audit", "user_reported"},
        "engineering_issues.status": {"open", "fixed"},
        "outcome.result": {"win", "loss", "inconclusive"},
        "element_type": {"headline", "subheadline", "cta", "microcopy", "layout"},
        "severity": {"Sev0", "Sev1", "Sev2"},
    }

    def enum_ok(field: str, value) -> None:
        check(f"example {field}={value!r} is in its documented enum",
              value is None or value in ENUMS[field], str(value))

    enum_ok("page.target", d["page"].get("target"))
    enum_ok("page.goal_source", d["page"].get("goal_source"))
    enum_ok("scope", latest.get("scope"))
    ps = latest.get("page_snapshot") or {}
    if "capture_method" in ps:
        enum_ok("capture_method", ps["capture_method"])
    for h in d["history"]:
        enum_ok("scope", h.get("scope"))
    for e in d["experiments"]:
        enum_ok("status_source", e.get("status_source"))
        if e.get("outcome"):
            enum_ok("outcome.result", e["outcome"].get("result"))
    for idea in latest["pxl"]["ideas"]:
        enum_ok("element_type", idea.get("element_type"))
    for e in d["experiments"]:
        enum_ok("element_type", e.get("element_type"))
    for e in d["engineering_issues"]:
        enum_ok("engineering_issues.status", e.get("status"))
        enum_ok("severity", e.get("severity"))
        check(f"{e['id']} source is a non-empty token (open set)",
              isinstance(e.get("source"), str) and bool(e["source"]))

    # Every closed enum must actually be documented in the schema's own table —
    # an enumerated field the table omits is how `severity` and `element_type`
    # drifted (three spellings of "subhead" across SKILL.md and the template).
    for field, values in ENUMS.items():
        name = field.split(".")[-1]
        documented = [v for v in values if f"`{v}`" in schema_src]
        check(f"{name}'s allowed values are all documented in the schema",
              len(documented) == len(values),
              f"undocumented: {sorted(set(values) - set(documented))}")

    print("\n== eval harness wiring ==")
    run_src = RUN_EVALS.read_text()
    grade_src = GRADE_EVALS.read_text()
    config_src = HARNESS_CONFIG.read_text()
    loop_src = RUN_LOOP.read_text()
    loaded = set(re.findall(r'\("(references/[\w-]+\.md)"', run_src))
    referenced = set(re.findall(r"`(references/[\w-]+\.md)`", skill_src))
    missing = referenced - loaded
    check("every reference SKILL.md loads is injected by run_evals.py",
          not missing, f"missing: {sorted(missing)}")
    cases = json.loads((SKILL_DIR / "evals" / "evals.json").read_text())
    ids = {c["id"] for c in cases}
    check("eval set covers the profile write path",
          len({i for i in ids if i.startswith("profile-")}) >= 4,
          f"found {sorted(i for i in ids if i.startswith('profile-'))}")
    check("eval ids are unique", len(ids) == len(cases))
    # The recovery path is the only rule in this skill whose failure destroys
    # data, so it needs model-level coverage, not just the static checks above.
    # Match on PROMPTS, not the whole blob: the unsupported-version case's own
    # assertions say "explicitly NOT corrupt", so a substring search over the
    # corpus reports corrupt-path coverage that doesn't exist.
    prompts = [c["prompt"] for c in cases]
    for kind, needle in (("corrupt profile", "no longer parses"),
                         ("unsupported schema version", "schema_version")):
        hits = [c["id"] for c, p in zip(cases, prompts) if needle in p]
        check(f"an eval prompt sets up the {kind} recovery write", bool(hits), str(hits))
    asserts = " ".join(a["description"] for c in cases for a in c["assertions"])
    check("a recovery eval asserts the no-clobber filename rule",
          "exclusive creation" in asserts and "check-then-overwrite" in asserts)
    check("a recovery eval asserts the timestamped (not audit_id) filename",
          "<YYYYMMDD-HHMMSS>" in asserts)
    # The 1.0 -> 1.1 migration and the focused-run rebuild are both places where
    # the safe behaviour is "do less than you could" — exactly what a model
    # trying to be helpful gets wrong, so both need model-level coverage.
    check("an eval covers the legacy schema migration",
          any("1.0" in c["prompt"] and "schema_version" in c["prompt"] for c in cases))
    check("the migration eval forbids inferring a fix from a legacy profile",
          "Leaves the legacy engineering issue open" in asserts)
    check("an eval covers the full-to-focused engineering_checks_run rebuild",
          "rather than carrying forward the previous full audit's check tokens" in asserts)
    rebuild_eval = next(
        (case for case in cases
         if case["id"] == "profile-focused-run-rebuilds-checks"),
        None,
    )
    rebuild_asserts = (
        " ".join(assertion["description"] for assertion in rebuild_eval["assertions"])
        if rebuild_eval else ""
    )
    check("focused rebuild assertion names the three actually carried blocks",
          "three unmeasured blocks (page_snapshot, metrics, pxl)" in rebuild_asserts
          and "four measured blocks" not in rebuild_asserts)
    focused_eval = next(
        (case for case in cases
         if case["id"] == "profile-focused-run-delta-provenance"),
        None,
    )
    focused_asserts = (
        " ".join(assertion["description"] for assertion in focused_eval["assertions"])
        if focused_eval else ""
    )
    check("focused-run provenance eval supplies exact source data",
          focused_eval is not None
          and "2026-06-12" in focused_eval["prompt"]
          and "value_proposition=3" in focused_eval["prompt"]
          and "value_proposition=4" in focused_eval["prompt"])
    check("focused-run provenance eval asserts exact sources and deltas",
          "metrics:null, lift:2026-06-12, pxl:null" in focused_asserts
          and "lift_total_delta exactly 3" in focused_asserts
          and "distraction -1" in focused_asserts)
    check("recovery evals require complete standalone profiles",
          "complete standalone current-run profile" in asserts)
    check("eval set covers audit-owned status reconciliation",
          "profile-audit-status-reconciliation" in ids)
    check("eval set covers exact engineering rechecks",
          "profile-engineering-check-proof" in ids)
    for label, source in (
        ("run_evals.py", run_src),
        ("grade_evals.py", grade_src),
        ("run_loop.py", loop_src),
    ):
        effective_source = (
            source
            + config_src
            + (run_src if label == "grade_evals.py" else "")
        )
        check(f"{label} isolates Claude customizations",
              "ISOLATED_CLAUDE_ARGS" in source
              and "--safe-mode" in effective_source
              and "--no-session-persistence" in effective_source)
        check(f"{label} disables built-in model tools",
              "ISOLATED_CLAUDE_ARGS" in source
              and '"--tools", ""' in effective_source)
        check(f"{label} caps per-call model spending",
              "--max-budget-usd" in source)
        check(f"{label} pins an explicit model for paid calls",
              '"--model"' in source and "required=True" in source)
        check(f"{label} exposes paid-call timeouts",
              "timeout-seconds" in source)
    check("all harness entry points import one shared environment definition",
          all("from harness_config import" in source
              for source in (run_src, grade_src, loop_src)))
    check("no harness entry point derives a repo root by fixed parent depth",
          all("parents[1]" not in source
              for source in (run_src, grade_src, loop_src)))
    config_spec = importlib.util.spec_from_file_location(
        "cro_harness_config", HARNESS_CONFIG)
    config_mod = importlib.util.module_from_spec(config_spec)
    assert config_spec and config_spec.loader
    config_spec.loader.exec_module(config_mod)
    with tempfile.TemporaryDirectory() as layout_dir:
        layout_root = Path(layout_dir)
        repo = layout_root / "repo"
        repo_skill = repo / "skills" / "cro"
        repo_skill.mkdir(parents=True)
        (repo / ".git").mkdir()
        loose_skill = layout_root / "working" / "cro"
        loose_skill.mkdir(parents=True)
        check("shared path resolver finds a repository checkout by marker",
              config_mod.resolve_project_root(repo_skill) == repo.resolve())
        check("shared path resolver keeps a loose copy beside its working folder",
              config_mod.resolve_project_root(loose_skill)
              == loose_skill.parent.resolve())
    check("eval runner supports safe output resume",
          "--resume" in run_src
          and "resumable_output(out_path, prompt, system_prompt, model)" in run_src
          and "request_sha256" in run_src
          and "output_sha256" in run_src)
    check("grader resume binds cache to outputs, assertions, contract, and model",
          "--resume" in grade_src
          and "_output_sha256" in grade_src
          and "_assertions_sha256" in grade_src
          and "_eval_prompt_sha256" in grade_src
          and "_grader_contract_sha256" in grade_src
          and "_grader_model" in grade_src)
    check("run_loop has no unsafe whole-suite timeout",
          "timeout=600" not in loop_src and "timeout=300" not in loop_src)
    check("run_loop restores the prior best after every candidate",
          "finally:" in loop_src and "write_description(best_description)" in loop_src)
    # The baseline must clear the SAME completeness bar as a candidate. When it
    # didn't, a baseline averaged over the evals that happened to grade was
    # compared against candidates required to grade all of them — so the loop
    # chose on the difference between eval subsets, not between descriptions.
    baseline_block = loop_src.partition("── Baseline ──")[2].partition("Optimization rounds")[0]
    check("run_loop holds the baseline to the candidate completeness bar",
          "_is_infra_failure(bench)" in baseline_block)
    check("run_loop no longer accepts a partial baseline",
          "accept any non-empty grading result" not in loop_src
          and "only abort if NO eval produced a real score" not in loop_src)
    # Iteration numbers used to restart at LOOP_ITER_BASE every invocation, so a
    # second run wrote into the first run's directories — and nothing clears
    # them, while run_claude writes no file when interrupted.
    check("run_loop allocates a fresh iteration block per run",
          "allocate_iteration_base()" in loop_src
          and "iter_counter = baseline_iter + 1" in loop_src)
    loop_example = re.search(
        r"python3 run_loop\.py .*?--rounds (\d+) .*?--candidates (\d+) "
        r".*?--max-model-calls (\d+)",
        loop_src,
    )
    if loop_example:
        example_rounds, example_candidates, example_cap = map(
            int, loop_example.groups())
        required_calls = (
            example_rounds
            + (1 + example_rounds * example_candidates) * len(cases) * 2
        )
    else:
        example_cap = required_calls = -1
    check("run_loop full-suite usage cap matches the current eval count",
          loop_example is not None and example_cap == required_calls,
          f"cap={example_cap}, required={required_calls}")
    # re.sub interprets escapes in a replacement *string*: a backslash in a
    # candidate raised re.error (not a ValueError, so the caller's guard missed
    # it), and a literal \n silently broke the frontmatter. Exercised rather
    # than grepped — the fixed and broken forms differ only by a `lambda`, so
    # source text cannot tell them apart.
    loop_spec = importlib.util.spec_from_file_location("cro_run_loop", RUN_LOOP)
    loop_mod = importlib.util.module_from_spec(loop_spec)
    assert loop_spec and loop_spec.loader
    loop_spec.loader.exec_module(loop_mod)
    with tempfile.TemporaryDirectory() as loop_dir:
        stub = Path(loop_dir) / "SKILL.md"
        stub.write_text("---\nname: cro\ndescription: >\n  old text here\n---\n\n# body\n")
        loop_mod.SKILL_MD = stub
        backslashed = r"Audit C:\path pages and \1 references"
        try:
            loop_mod.write_description(backslashed)
            survived = loop_mod.read_current_description() == backslashed
        except Exception:  # noqa: BLE001 - re.error is the failure being tested
            survived = False
        check("write_description survives a backslash in a candidate", survived)
        check("...and leaves the frontmatter intact",
              stub.read_text().count("---") == 2 and "# body" in stub.read_text())
    # A typo'd --eval-ids used to count as 0 selected evals, so run_loop planned
    # 0 output calls and the mistake only surfaced inside the run_evals.py
    # subprocess. The count function itself must reject the typo, by name.
    real_id = sorted(ids)[0]
    check("selected_eval_count accepts a real eval id",
          loop_mod.selected_eval_count(real_id) == 1)
    try:
        loop_mod.selected_eval_count(f"{real_id},no-such-eval")
        typo_rejected = False
    except SystemExit as stop:
        typo_rejected = "no-such-eval" in str(stop) and real_id not in str(stop)
    check("selected_eval_count rejects a typo'd id and names only it",
          typo_rejected)
    try:
        loop_mod.selected_eval_count(",")
        empty_rejected = False
    except SystemExit as stop:
        empty_rejected = "selects no evals" in str(stop)
    check("selected_eval_count rejects an empty --eval-ids selection",
          empty_rejected)
    check("grade_evals rebuilds benchmarks from authenticated grade records",
          "aggregate_grades = collect_cached_grades(" in grade_src
          and "benchmark = aggregate(aggregate_grades, aggregate_evals)" in grade_src)
    run_spec = importlib.util.spec_from_file_location(
        "cro_run_evals", RUN_EVALS)
    run_mod = importlib.util.module_from_spec(run_spec)
    assert run_spec and run_spec.loader
    run_spec.loader.exec_module(run_mod)
    with tempfile.TemporaryDirectory() as harness_dir:
        harness_root = Path(harness_dir)
        empty_output = harness_root / "empty.md"
        captured_commands = []

        class EmptyProcess:
            returncode = 0

            def communicate(self, timeout=None):
                return "", ""

        original_popen = run_mod.subprocess.Popen
        original_repo_root = run_mod.REPO_ROOT
        run_mod.REPO_ROOT = harness_root
        run_mod.subprocess.Popen = lambda command, **kwargs: (
            captured_commands.append(command) or EmptyProcess())
        try:
            empty_ok = run_mod.run_claude(
                "prompt",
                "system",
                empty_output,
                model="exact-test-model",
                timeout=1,
                max_budget_usd=0.01,
            )
        finally:
            run_mod.subprocess.Popen = original_popen
            run_mod.REPO_ROOT = original_repo_root
        check("exit-zero empty stdout is a harness failure",
              not empty_ok
              and empty_output.read_text().startswith("[EMPTY")
              and not run_mod.valid_output(empty_output)
              and not run_mod.output_metadata_path(empty_output).exists())
        check("output runner passes the pinned model to Claude",
              any(
                  "--model" in command
                  and command[command.index("--model") + 1] == "exact-test-model"
                  for command in captured_commands
              ))
        complete_output = harness_root / "complete.md"
        complete_output.write_text("gradeable response")
        run_mod.write_output_metadata(
            complete_output,
            "original prompt",
            "original system",
            "exact-test-model",
        )
        check("resume authenticates model, prompt, context, and output bytes",
              run_mod.resumable_output(
                  complete_output,
                  "original prompt",
                  "original system",
                  "exact-test-model",
              )
              and not run_mod.resumable_output(
                  complete_output,
                  "changed prompt",
                  "original system",
                  "exact-test-model",
              )
              and not run_mod.resumable_output(
                  complete_output,
                  "original prompt",
                  "changed system",
                  "exact-test-model",
              )
              and not run_mod.resumable_output(
                  complete_output,
                  "original prompt",
                  "original system",
                  "different-model",
              ))
        complete_output.write_text("changed response")
        check("resume rejects an output whose bytes changed",
              not run_mod.resumable_output(
                  complete_output,
                  "original prompt",
                  "original system",
                  "exact-test-model",
              ))
    grade_spec = importlib.util.spec_from_file_location(
        "cro_grade_evals", GRADE_EVALS)
    grade_mod = importlib.util.module_from_spec(grade_spec)
    assert grade_spec and grade_spec.loader
    grade_spec.loader.exec_module(grade_mod)
    grade_assertions = [
        {"id": "first", "description": "first", "weight": 1},
        {"id": "second", "description": "second", "weight": 1},
    ]
    valid_grade = {
        "scores": {"first": 1, "second": 0},
        "notes": "valid binary result",
    }
    check("grader accepts an exact binary assertion map",
          grade_mod.validate_grade_payload(valid_grade, grade_assertions)
          == valid_grade)
    with tempfile.TemporaryDirectory() as failed_grade_dir:
        failed_output = Path(failed_grade_dir) / "with-skill.md"
        failed_output.write_text("gradeable response")

        class FailedGradeProcess:
            returncode = 1

            def communicate(self, timeout=None):
                return json.dumps(valid_grade), "simulated CLI failure"

        original_grade_popen = grade_mod.subprocess.Popen
        grade_mod.subprocess.Popen = lambda command, **kwargs: FailedGradeProcess()
        try:
            failed_grade = grade_mod.grade_one(
                {
                    "id": "failed-grade",
                    "prompt": "probe",
                    "assertions": grade_assertions,
                },
                failed_output,
                model="exact-grader-model",
                timeout=1,
                max_budget_usd=0.01,
            )
        finally:
            grade_mod.subprocess.Popen = original_grade_popen
        check("grader rejects parseable stdout from a failed Claude process",
              failed_grade is None)
    with tempfile.TemporaryDirectory() as grade_dir:
        grade_root = Path(grade_dir)
        output_path = grade_root / "with-skill.md"
        grades_path = grade_root / "with-skill.grades.json"
        output_path.write_text("first output")
        grades_path.write_text(json.dumps(
            grade_mod.grade_record(
                valid_grade,
                grade_assertions,
                output_path,
                "exact-grader-model",
                "original eval prompt",
            )
        ))
        check("resume accepts a grade bound to unchanged inputs",
              grade_mod.load_cached_grade(
                  grades_path,
                  output_path,
                  grade_assertions,
                  "exact-grader-model",
                  "original eval prompt",
              ) == valid_grade)
        output_path.write_text("changed output")
        check("resume rejects grades after output bytes change",
              grade_mod.load_cached_grade(
                  grades_path,
                  output_path,
                  grade_assertions,
                  "exact-grader-model",
                  "original eval prompt",
              ) is None)
        output_path.write_text("first output")
        changed_assertions = clone(grade_assertions)
        changed_assertions[0]["description"] = "changed rubric"
        check("resume rejects grades after assertions change",
              grade_mod.load_cached_grade(
                  grades_path,
                  output_path,
                  changed_assertions,
                  "exact-grader-model",
                  "original eval prompt",
              ) is None)
        check("resume rejects grades after the grader model changes",
              grade_mod.load_cached_grade(
                  grades_path,
                  output_path,
                  grade_assertions,
                  "different-grader-model",
                  "original eval prompt",
              ) is None)
        check("resume rejects grades after the eval prompt changes",
              grade_mod.load_cached_grade(
                  grades_path,
                  output_path,
                  grade_assertions,
                  "exact-grader-model",
                  "changed eval prompt",
              ) is None)
    with tempfile.TemporaryDirectory() as rebuild_dir:
        rebuild_root = Path(rebuild_dir)
        rebuild_context = grade_mod.build_skill_context()
        rebuild_evals = [
            {
                "id": "cached-a",
                "prompt": "prompt a",
                "assertions": grade_assertions,
            },
            {
                "id": "cached-b",
                "prompt": "prompt b",
                "assertions": grade_assertions,
            },
        ]
        for eval_def in rebuild_evals:
            eval_dir = rebuild_root / eval_def["id"]
            eval_dir.mkdir()
            for condition in grade_mod.CONDITIONS:
                cached_output = eval_dir / f"{condition}.md"
                cached_output.write_text(
                    f"{eval_def['id']} {condition} response")
                run_mod.write_output_metadata(
                    cached_output,
                    eval_def["prompt"],
                    (
                        rebuild_context
                        if condition == "with-skill"
                        else grade_mod.BASELINE_SYSTEM
                    ),
                    "exact-output-model",
                )
                cached_grade = eval_dir / f"{condition}.grades.json"
                cached_grade.write_text(json.dumps(grade_mod.grade_record(
                    valid_grade,
                    eval_def["assertions"],
                    cached_output,
                    "exact-grader-model",
                    eval_def["prompt"],
                )))
        complete_cache = grade_mod.collect_cached_grades(
            rebuild_evals,
            rebuild_root,
            "exact-grader-model",
            rebuild_context,
        )
        complete_benchmark = grade_mod.aggregate(
            complete_cache,
            rebuild_evals,
        )
        check("authenticated benchmark rebuild preserves unselected cached evals",
              set(complete_benchmark["evals"]) == {"cached-a", "cached-b"}
              and all(
                  complete_benchmark["evals"][eval_id]["conditions"][condition][
                      "score"] is not None
                  for eval_id in ("cached-a", "cached-b")
                  for condition in grade_mod.CONDITIONS
              ))
        mixed_output = rebuild_root / "cached-b" / "baseline.md"
        run_mod.write_output_metadata(
            mixed_output,
            "prompt b",
            grade_mod.BASELINE_SYSTEM,
            "different-output-model",
        )
        check("grader detects mixed producer models within one iteration",
              grade_mod.authenticated_output_models(
                  rebuild_evals,
                  rebuild_root,
                  rebuild_context,
              ) == {"exact-output-model", "different-output-model"})
        run_mod.write_output_metadata(
            mixed_output,
            "prompt b",
            grade_mod.BASELINE_SYSTEM,
            "exact-output-model",
        )
        (rebuild_root / "cached-b" / "baseline.md").write_text(
            "stale replacement")
        stale_cache = grade_mod.collect_cached_grades(
            rebuild_evals,
            rebuild_root,
            "exact-grader-model",
            rebuild_context,
        )
        stale_benchmark = grade_mod.aggregate(stale_cache, rebuild_evals)
        check("benchmark rebuild drops only the stale grade",
              stale_benchmark["evals"]["cached-a"]["conditions"]["baseline"][
                  "score"] is not None
              and stale_benchmark["evals"]["cached-b"]["conditions"]["with-skill"][
                  "score"] is not None
              and stale_benchmark["evals"]["cached-b"]["conditions"]["baseline"][
                  "score"] is None)
    malformed_grades = [
        {"scores": {"first": 2, "second": 0}, "notes": "out of range"},
        {"scores": {"first": True, "second": 0}, "notes": "bool"},
        {"scores": {"first": 1}, "notes": "missing"},
        {"scores": {"first": 1, "second": 0, "extra": 1}, "notes": "extra"},
        {"scores": {"first": 1, "second": 0}, "notes": 7},
    ]
    check("grader rejects non-binary, bool, missing, extra, and malformed grades",
          all(grade_mod.validate_grade_payload(candidate, grade_assertions) is None
              for candidate in malformed_grades))
    probe_eval = {
        "id": "grade-probe",
        "prompt": "probe",
        "assertions": grade_assertions,
    }
    malformed_benchmark = grade_mod.aggregate(
        {
            "grade-probe": {
                "with-skill": malformed_grades[0],
                "baseline": None,
            }
        },
        [probe_eval],
    )
    check("invalid grader output becomes infrastructure failure, never 200%",
          malformed_benchmark["summary"]["with-skill"] is None
          and malformed_benchmark["evals"]["grade-probe"]["conditions"][
              "with-skill"]["score"] is None)
    # The negative evals are the only proxy for scope discipline in a harness
    # that injects the skill unconditionally. If the system preamble restates a
    # rule those evals test, the model answers from the preamble and the eval
    # grades the preamble instead of SKILL.md. Prose asking future editors to
    # keep it clean is not enough — this is the enforcement.
    preamble = re.search(r'SYSTEM_PROMPT_PREAMBLE\s*=\s*"""(.*?)"""', run_src, re.S)
    check("run_evals.py exposes a findable SYSTEM_PROMPT_PREAMBLE", preamble is not None)
    if preamble:
        # Each token is a rule the assertions in evals.json test for: the
        # routing targets, the delegation mechanism, the scope boundary, the
        # report vocabulary, and the unavailable-data handling.
        leaks = [
            tok for tok in (
                "ga4", "google-search-console", "marketing-voice", "session-replay",
                "public page", "localhost", "nine-section", "lift", "pxl", "hypothesis doc",
                "fabricat", "no data", "heuristic-only", "data api", "mcp",
                "standalone", "copy rewrite", "decline",
            )
            if tok in preamble.group(1).lower()
        ]
        check("the eval preamble restates no rule the evals test",
              not leaks, f"leaked: {leaks}")

    print()
    if failures:
        print(f"{len(failures)} FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all checks pass")
    return 0


if __name__ == "__main__":
    # A crash must never look like a pass, and must never be mistaken for
    # "only the failures printed so far exist" — an exception mid-run means
    # every later check went unevaluated.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - surfacing any breakage is the point
        import traceback
        traceback.print_exc()
        print(f"\nCRASHED before finishing: {type(exc).__name__}: {exc}")
        print("Checks after this point did NOT run — fix the crash, then re-read the results.")
        sys.exit(2)
