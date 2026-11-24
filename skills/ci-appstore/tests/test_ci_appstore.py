"""End-to-end checks for the ci-appstore scripts, run against the fictional demo.

Runnable with plain python3 or pytest (needs jsonschema + pyyaml):

    python3 tests/test_ci_appstore.py
    python3 -m pytest -q tests
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
DEMO = SKILL / "examples" / "demo"
SCRIPTS = SKILL / "scripts"
TODAY = "2026-09-15"  # the demo was collected on 2026-09-01


def run(script, *args):
    proc = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def copy_demo():
    tmp = Path(tempfile.mkdtemp(prefix="ci-appstore-test-"))
    shutil.copytree(DEMO, tmp / "demo")
    return tmp / "demo"


def edit_profile(data_dir, slug, mutate):
    path = data_dir / "profiles" / f"{slug}.json"
    profile = json.loads(path.read_text())
    mutate(profile)
    path.write_text(json.dumps(profile, indent=2))


def validate(data_dir, today=TODAY):
    return run("validate_profiles.py", "--data-dir", data_dir, "--today", today)


# ---------------------------------------------------------------- happy path --
def test_demo_profiles_are_valid():
    code, out = validate(DEMO)
    assert code == 0, out
    assert "4 profile(s) valid" in out


def test_demo_snapshot_is_valid():
    snaps = sorted((DEMO / "snapshots" / "2026-08-01").glob("*.json"))
    code, out = run("validate_profiles.py", "--data-dir", DEMO, "--today", TODAY, *snaps)
    assert code == 0, out


def test_report_renders_every_section_with_computed_scores():
    code, md = run("render_report.py", "--data-dir", DEMO, "--date", "2026-09-01", "--stdout")
    assert code == 0, md
    for n in range(1, 13):
        assert f"## {n}. " in md, f"section {n} missing"
    assert "Acme Reviews vs 3 competitors" in md
    # 4*.25 + 4*.20 + 3*.20 + 4*.20 + 4*.15 = 3.8 — computed, never hand-typed
    assert "| **Acme Reviews** | 4 | 4 | 3 | 4 | 4 | **3.8** |" in md
    assert "Product capability matrix vs Acme Reviews" in md
    assert "None" not in md, "a missing value leaked into the report as Python None"


def test_report_file_is_written_to_the_data_dir():
    data = copy_demo()
    code, out = run("render_report.py", "--data-dir", data, "--date", "2026-09-01")
    assert code == 0, out
    assert (data / "reports" / "2026-09-01-appstore.md").exists()


def test_diff_surfaces_the_material_changes():
    code, out = run("diff_profiles.py", DEMO / "snapshots" / "2026-08-01", DEMO / "profiles")
    assert code == 0, out
    for expected in ("PRICING: Free · $39 · $299  ->  Free · $49 · $299",
                     "REVIEWS: 3050 -> 3410 (+360)",
                     "KEYWORD 'photo reviews': #6 -> #4",
                     "CAPABILITY 'import_from_other_apps': parity -> competitor_advantage",
                     "NEW complaint theme: Video uploads fail on mobile"):
        assert expected in out, f"diff missed: {expected}"
    assert "Acme Reviews" not in out, "an unchanged profile was reported as changed"


def test_diff_of_identical_sets_reports_nothing():
    code, out = run("diff_profiles.py", DEMO / "profiles", DEMO / "profiles")
    assert code == 0 and "No material changes." in out, out


# ------------------------------------------------------- the validator bites --
def _rejects(slug, mutate, expect, today=TODAY):
    data = copy_demo()
    edit_profile(data, slug, mutate)
    code, out = validate(data, today)
    assert code == 1, f"validator accepted a broken profile:\n{out}"
    assert expect in out, f"expected {expect!r} in:\n{out}"


def test_rejects_unknown_capability_verdict():
    _rejects("globex-reviews",
             lambda p: p["layers"]["app_store"]["capabilities"]["matrix"].update(q_and_a="better"),
             "[schema:layer:app_store]")


def test_rejects_pricing_without_a_backing_claim():
    _rejects("globex-reviews",
             lambda p: p.update(claims=[c for c in p["claims"] if ".pricing" not in c["field"]]),
             "pricing present but no current pricing claim")


def test_rejects_scores_without_a_backing_claim():
    _rejects("initech-ratings",
             lambda p: p.update(claims=[c for c in p["claims"] if not c["field"].startswith("scores")]),
             "scores present but no current scores claim")


def test_rejects_layers_populated_out_of_sync():
    _rejects("umbrella-ugc", lambda p: p.update(layers_populated=[]), "layers_populated")


def test_rejects_a_claim_pointing_at_a_missing_field():
    _rejects("acme-reviews",
             lambda p: p["claims"][0].update(field="layers.app_store.pricing.not_a_field"),
             "claim field does not resolve")


def test_rejects_an_unregistered_layer():
    def add_layer(p):
        p["layers"]["mystery"] = {"meta": {"layer_id": "mystery", "collected_by": "x",
                                           "collected_at": "2026-09-01", "layer_version": "1.0",
                                           "status": "populated"}}
        p["layers_populated"].append("mystery")
    _rejects("acme-reviews", add_layer, "layer 'mystery' is not registered")


def test_rejects_a_planned_layer_being_populated():
    def add_layer(p):
        p["layers"]["pricing"] = {"meta": {"layer_id": "pricing", "collected_by": "unassigned",
                                           "collected_at": "2026-09-01", "layer_version": "1.0",
                                           "status": "populated"}}
        p["layers_populated"].append("pricing")
    _rejects("acme-reviews", add_layer, "registry status is not 'active'")


def test_rejects_a_slug_that_does_not_match_its_filename():
    _rejects("acme-reviews", lambda p: p.update(slug="someone-else"), "does not match filename")


def test_rejects_claims_past_the_refresh_horizon():
    _rejects("acme-reviews", lambda p: None, "older than 90d", today="2027-06-01")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for n, f in tests:
        try:
            f()
            print(f"  ok    {n}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {n}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
