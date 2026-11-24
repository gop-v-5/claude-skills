#!/usr/bin/env python3
"""
CRO skill description optimization loop.

Iterates on the SKILL.md `description:` field to find the version that produces
the highest benchmark score on the eval set.

WHAT THIS DOES NOT MEASURE — read before trusting a result. This loop does not
test whether a description causes the skill to be SELECTED. run_evals.py injects
the whole skill into every call unconditionally, so the skill is always in
context no matter what the description says; the description is scored only for
the effect its wording has on behaviour once the skill is already loaded. That
is a real effect and worth optimising, but it is not the router. A description
that wins here may still fail to trigger in a live harness, and one that loses
here may trigger perfectly well. Judging the trigger line requires a harness
that registers the skill WITHOUT injecting it, and offers competing skills to
choose between — which this suite does not do. See README.md.

Each iteration:
  1. Reads current SKILL.md description
  2. Uses claude to propose N candidate descriptions
  3. Runs the eval suite (with-skill condition only) for each candidate
  4. Grades all outputs
  5. Picks the best-scoring description
  6. Writes it back to SKILL.md if it beats the current best
  7. Repeats for --rounds rounds

Usage:
    python3 run_loop.py --model EXACT_MODEL_ID --rounds 1 --candidates 1 --max-model-calls 149
    python3 run_loop.py --model EXACT_MODEL_ID --eval-ids id-a,id-b --rounds 1 --candidates 2 --max-model-calls 13
    python3 run_loop.py --model EXACT_MODEL_ID --dry-run --max-model-calls 3

The explicit call cap is intentional: a full candidate loop makes two model
calls per eval (output + grader), plus proposer calls.
"""

from __future__ import annotations  # PEP 604 "X | None" annotations must work on Python 3.9

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

_LOCAL_EVALS_DIR = Path(__file__).resolve().parent / "evals"
if str(_LOCAL_EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(_LOCAL_EVALS_DIR))

from harness_config import (  # noqa: E402 - local import path is established above
    EVALS_DIR,
    EVALS_JSON,
    GRADER_BUDGET_USD,
    GRADER_TIMEOUT_SECONDS,
    ISOLATED_CLAUDE_ARGS,
    OUTPUT_BUDGET_USD,
    OUTPUT_TIMEOUT_SECONDS,
    REPO_ROOT,
    SKILL_MD,
    WORKSPACE,
    nonempty_model,
    positive_float,
    positive_int,
)

# Iteration numbers 100+ are reserved for the optimization loop
# so they don't collide with manually-run iterations 1-99
LOOP_ITER_BASE = 100

PROPOSER_SYSTEM = """\
You are an expert at writing Claude Code skill trigger descriptions.
A skill description is the text in the SKILL.md frontmatter 'description:' field that
tells Claude Code when to load and use this skill. It is matched against user queries.

CRITICAL — this skill audits a specific public page. Every candidate
description you produce MUST:
- State that the skill audits a page given by URL — any public website page, or
  a Shopify App Store app listing (apps.shopify.com/<app>).
- Carry an explicit negative boundary that the skill must NOT trigger without a
  page URL (general CRO advice is not a trigger).
Never propose a description that drops the page-URL requirement — that erases
the skill's most important boundary.

Effective descriptions:
- Cover the full range of user intents that should trigger the skill, always
  scoped to a specific page URL
- Include specific keywords users naturally say (audit this page for CRO, why
  isn't this converting, plan an A/B test, build a test backlog, funnel drop-off,
  run a LIFT review, write a hypothesis doc, etc.)
- Are precise enough to avoid false positives on standalone data-lookup or
  copy-rewrite requests (which route to ga4 / google-search-console / marketing-voice)
- Mention the framework scope (CRO audit, LIFT heuristic, PXL prioritization, landing-page conversion)
- Cover the main CRO intents this skill serves: full CRO/conversion audit of a
  page, "why isn't this page converting", funnel / signup drop-off on a specific
  page, A/B test ideas or an experiment backlog for a page, "what should we
  test", LIFT (heuristic) review of a page, PXL test prioritization, A/B test
  hypothesis docs / full test specs, copy/CTA/headline variants produced inside
  an audit (single-variable), and focused slices of the above (a LIFT-only
  review, a backlog-only ask, or hypothesis-docs-only) — all on a specific page URL.
- Keep the boundary sharp so the trigger does NOT fire on standalone data
  lookups or untethered copy edits: bare GA4 metric lookups route to ga4, bare
  Search Console query/CTR/position lookups route to google-search-console, and
  one-off copy / CTA / headline rewrites not tied to an audit route to
  marketing-voice. A URL plus a date range alone (no audit/test/LIFT intent) is
  NOT a CRO trigger.

The description field can be multi-line using YAML folded block scalar (description: >).
Favor coverage over brevity, but the validator hard-rejects any description over
1024 characters or containing the angle-bracket characters, so keep every
candidate under 1024 chars and never use angle brackets.

Output ONLY a JSON array of description strings. No other text, no markdown fencing.
Each string should be the complete description value (without the 'description: >' prefix).
"""

PROPOSER_PROMPT = """\
Current SKILL.md description:
"{current_description}"

Current benchmark score (with-skill condition): {current_score}

Eval prompts being tested:
{eval_prompts}

Assertion failures in current run:
{weaknesses}

Propose {n} alternative description strings that might improve the score.
Focus on covering intents or keywords that appear to be under-served.
Output a JSON array of {n} strings only.
"""


def read_current_description() -> str:
    """Read the description field from SKILL.md, handling both single-line and multi-line block scalar."""
    content = SKILL_MD.read_text()
    m = re.search(r"^description:\s*>\s*\n((?:[ \t]+.+\n?)*)", content, re.MULTILINE)
    if m:
        lines = [line.strip() for line in m.group(1).splitlines() if line.strip()]
        return " ".join(lines)
    m = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def write_description(new_description: str):
    """Write a new description to SKILL.md, preserving the folded block scalar form."""
    new_description = " ".join(new_description.splitlines()).strip()
    # Guard: the validator rejects descriptions > 1024 chars or containing angle
    # brackets. The proposer is told to favor coverage over brevity, so refuse to
    # write a candidate that would make SKILL.md fail quick_validate.py.
    if len(new_description) > 1024 or "<" in new_description or ">" in new_description:
        raise ValueError(
            f"Refusing to write invalid description "
            f"(len={len(new_description)}, has_angle_brackets="
            f"{'<' in new_description or '>' in new_description}); "
            "would fail quick_validate.py."
        )
    content = SKILL_MD.read_text()
    # Both replacements MUST be callables. re.sub interprets escapes in a
    # replacement *string*, so a candidate containing a backslash either raises
    # re.error ("bad escape \p") — which is not a ValueError, so the caller's
    # guard misses it and the whole paid run dies — or, for \n, silently injects
    # a newline that breaks the YAML frontmatter. A callable is passed through
    # verbatim.
    updated = re.sub(
        r"^description:\s*>\s*\n(?:[ \t]+\S.*\n?)+",
        lambda _: f"description: >\n  {new_description}\n",
        content,
        flags=re.MULTILINE,
    )
    if updated == content:
        updated = re.sub(
            r"^(description:\s*)(.+)$",
            lambda m: f"{m.group(1)}>\n  {new_description}",
            content,
            flags=re.MULTILINE,
        )
    SKILL_MD.write_text(updated)


def allocate_iteration_base() -> int:
    """One past the highest iteration directory in use (never below LOOP_ITER_BASE).

    Iteration numbers used to restart at LOOP_ITER_BASE on every invocation, so
    a second run wrote into the first run's directories. Nothing clears them and
    run_claude does not write an output file when interrupted, so an eval killed
    by Ctrl-C left the previous run's answer in place for the grader to score as
    this candidate's. Allocating a fresh block keeps every run's evidence its
    own, and never deletes a previous run's outputs.
    """
    if not WORKSPACE.exists():
        return LOOP_ITER_BASE
    used = set()
    for child in WORKSPACE.iterdir():
        match = re.fullmatch(r"iteration-(\d+)", child.name)
        if match and child.is_dir():
            used.add(int(match.group(1)))
    # One past the highest in use, not the first gap: the candidates that follow
    # take baseline+1, +2, ... and a gap would put them back on top of an
    # existing directory.
    return max([LOOP_ITER_BASE - 1, *used]) + 1


def selected_eval_count(eval_ids: str | None = None) -> int:
    # Unknown ids are rejected here, not left for the run_evals.py subprocess:
    # a typo'd id used to count as 0, so the loop planned 0 output calls and
    # only failed after the baseline machinery had already started.
    evals = json.loads(EVALS_JSON.read_text())
    if not eval_ids:
        return len(evals)
    requested = {s.strip() for s in eval_ids.split(",") if s.strip()}
    available = {item["id"] for item in evals}
    missing = sorted(requested - available)
    if missing:
        raise SystemExit(f"Error: eval(s) not found in evals.json: {missing}")
    if not requested:
        raise SystemExit("Error: --eval-ids selects no evals")
    return len(requested)


def run_evals(
    iteration_num: int,
    eval_ids: str | None = None,
    *,
    model: str,
    max_budget_usd_per_call: float = OUTPUT_BUDGET_USD,
    timeout_seconds: int = OUTPUT_TIMEOUT_SECONDS,
) -> bool:
    """Run with-skill condition for all evals at iteration_num.

    If eval_ids is set (comma-separated), passes --eval-ids through so only
    that subset runs.
    """
    cmd = [sys.executable, str(EVALS_DIR / "run_evals.py"),
           "--iteration", str(iteration_num), "--condition", "with-skill",
           "--model", model,
           "--timeout-seconds", str(timeout_seconds),
           "--max-budget-usd-per-call", str(max_budget_usd_per_call),
           "--max-model-calls", str(selected_eval_count(eval_ids))]
    if eval_ids:
        cmd += ["--eval-ids", eval_ids]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    print(result.stdout.rstrip())
    if result.returncode != 0:
        print(f"  [WARN] run_evals exited {result.returncode}: {result.stderr[:200]}")
    return result.returncode == 0


def grade_evals(
    iteration_num: int,
    eval_ids: str | None = None,
    *,
    model: str,
    max_budget_usd_per_call: float = GRADER_BUDGET_USD,
    timeout_seconds: int = GRADER_TIMEOUT_SECONDS,
) -> dict:
    """Grade with-skill outputs and return the benchmark dict.

    If eval_ids is set (comma-separated), passes --eval-ids through. Every loop
    candidate uses a fresh iteration directory, so its benchmark covers exactly
    that requested subset.
    """
    cmd = [sys.executable, str(EVALS_DIR / "grade_evals.py"),
           "--iteration", str(iteration_num),
           "--model", model,
           "--timeout-seconds", str(timeout_seconds),
           "--max-budget-usd-per-call", str(max_budget_usd_per_call),
           "--max-model-calls", str(selected_eval_count(eval_ids))]
    if eval_ids:
        cmd += ["--eval-ids", eval_ids]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    print(result.stdout.rstrip())
    if result.returncode != 0:
        print(f"  [WARN] grade_evals exited {result.returncode}: {result.stderr[:200]}")
        return {}

    bench_path = WORKSPACE / f"iteration-{iteration_num}" / "benchmark.json"
    if bench_path.exists():
        return json.loads(bench_path.read_text())
    return {}


def extract_score(benchmark: dict) -> float:
    return benchmark.get("summary", {}).get("with-skill") or 0.0


def _is_infra_failure(benchmark: dict) -> bool:
    """True if grading did not produce real scores for every eval — distinct from a real 0% result.

    A real 0% score leaves every per-eval entry with a numeric score; an
    infrastructure failure (missing outputs, grader errors) leaves no evals
    or at least one with-skill condition set to None. Partial grading
    failures are rejected too — a benchmark is only usable when every eval
    produced a real score.
    """
    if not benchmark:
        return True
    evals_data = benchmark.get("evals")
    if not evals_data:
        return True
    return any(
        eval_data.get("conditions", {}).get("with-skill", {}).get("score") is None
        for eval_data in evals_data.values()
    )


def extract_weaknesses(benchmark: dict) -> str:
    lines = []
    for eval_id, eval_data in benchmark.get("evals", {}).items():
        cond_data = eval_data.get("conditions", {}).get("with-skill", {})
        raw = cond_data.get("raw", {})
        notes = cond_data.get("notes", "")
        failed = [aid for aid, score in raw.items() if score == 0]
        if failed:
            lines.append(f"{eval_id}: failed {failed}. Notes: {notes[:100]}")
    return "\n".join(lines) if lines else "No assertion failures."


def propose_candidates(current_description: str, current_score: float,
                       weaknesses: str, n: int,
                       *,
                       model: str,
                       eval_ids: str | None = None,
                       max_budget_usd_per_call: float = GRADER_BUDGET_USD,
                       timeout_seconds: int = GRADER_TIMEOUT_SECONDS) -> list[str]:
    evals = json.loads(EVALS_JSON.read_text())
    if eval_ids:
        requested = {s.strip() for s in eval_ids.split(",") if s.strip()}
        evals = [e for e in evals if e["id"] in requested]
    eval_prompts = "\n".join(f"  - {e['prompt']}" for e in evals)

    prompt = PROPOSER_PROMPT.format(
        current_description=current_description,
        current_score=f"{current_score:.1%}",
        eval_prompts=eval_prompts,
        weaknesses=weaknesses,
        n=n,
    )
    cmd = [
        "claude", "-p", "--output-format", "text",
        *ISOLATED_CLAUDE_ARGS,
        "--model", model,
        "--max-budget-usd", str(max_budget_usd_per_call),
        "--append-system-prompt", PROPOSER_SYSTEM,
        prompt,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    except KeyboardInterrupt:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        raise
    if proc.returncode != 0:
        detail = stderr.strip() or stdout.strip() or "no diagnostic output"
        print(
            f"  [WARN] Candidate proposer exited {proc.returncode}: "
            f"{detail[:300]}"
        )
        return []
    raw = stdout.strip()
    if not raw:
        print("  [WARN] Candidate proposer exited 0 without any candidates")
        return []
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        candidates = json.loads(raw)
        return [c for c in candidates if isinstance(c, str)][:n]
    except json.JSONDecodeError:
        print(f"  [WARN] Could not parse candidates JSON:\n{raw[:300]}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=positive_int, default=3)
    parser.add_argument("--candidates", type=positive_int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--model",
        type=nonempty_model,
        required=True,
        help="Exact Claude model ID to pin for proposer, output, and grader calls",
    )
    parser.add_argument(
        "--output-timeout-seconds",
        type=positive_int,
        default=OUTPUT_TIMEOUT_SECONDS,
        help="Per-output-call timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--grader-timeout-seconds",
        type=positive_int,
        default=GRADER_TIMEOUT_SECONDS,
        help="Per-grader/proposer-call timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--eval-ids",
        default=None,
        help="Comma-separated list of eval IDs to run (default: all evals in evals.json)",
    )
    parser.add_argument(
        "--max-model-calls",
        type=positive_int,
        default=100,
        help="Refuse when the planned output/grader/proposer calls exceed this cap (default: 100)",
    )
    parser.add_argument(
        "--max-budget-usd-per-call",
        type=positive_float,
        default=OUTPUT_BUDGET_USD,
        help="Hard Claude CLI budget cap for each output call (default: 2.0)",
    )
    parser.add_argument(
        "--max-grader-budget-usd-per-call",
        type=positive_float,
        default=GRADER_BUDGET_USD,
        help="Hard Claude CLI budget cap for each grader/proposer call (default: 0.5)",
    )
    args = parser.parse_args()

    eval_count = selected_eval_count(args.eval_ids)
    planned_calls = args.rounds if args.dry_run else (
        args.rounds
        + (1 + args.rounds * args.candidates) * eval_count * 2
    )
    if planned_calls > args.max_model_calls:
        print(
            f"Error: this loop plans up to {planned_calls} model calls "
            f"({eval_count} evals, {args.rounds} rounds, {args.candidates} candidates), "
            f"above --max-model-calls {args.max_model_calls}. "
            "Raise the cap explicitly after reviewing the cost."
        )
        sys.exit(2)

    print(f"\nCRO Skill Description Optimization Loop")
    print(f"Rounds: {args.rounds} | Candidates/round: {args.candidates}\n")

    original_description = read_current_description()
    best_description = original_description
    best_score = 0.0
    best_iteration = None
    weaknesses = "No prior run."
    history = []

    # ── Baseline ──────────────────────────────────────────────────────────
    print("── Establishing baseline ──")
    baseline_iter = allocate_iteration_base()
    if baseline_iter != LOOP_ITER_BASE:
        print(f"[INFO] iteration-{LOOP_ITER_BASE}+ already in use — this run starts at {baseline_iter}.")
    if not args.dry_run:
        write_description(best_description)
        if not run_evals(
            baseline_iter,
            args.eval_ids,
            max_budget_usd_per_call=args.max_budget_usd_per_call,
            model=args.model,
            timeout_seconds=args.output_timeout_seconds,
        ):
            print(
                "[WARN] Some baseline evals failed — the baseline is only "
                "usable if grading still produces a real score for every eval."
            )
        bench = grade_evals(
            baseline_iter,
            args.eval_ids,
            max_budget_usd_per_call=args.max_grader_budget_usd_per_call,
            model=args.model,
            timeout_seconds=args.grader_timeout_seconds,
        )

        # The baseline is held to the SAME completeness bar as a candidate
        # (_is_infra_failure). A partial baseline averages a different — and
        # usually easier, since timeouts hit the longest evals first — subset
        # than the complete set every candidate is required to produce, so the
        # two numbers are not comparable and the loop would accept or reject a
        # description on the difference between eval sets, not descriptions.
        # aggregate() emits an entry for every requested eval, scoring failures
        # as None, so "no None" is exactly "the complete requested set".
        evals_data = bench.get("evals", {}) if bench else {}
        if _is_infra_failure(bench):
            failed = [
                eid for eid, e in evals_data.items()
                if e.get("conditions", {}).get("with-skill", {}).get("score") is None
            ]
            detail = (
                f"{len(failed)} of {len(evals_data)} evals unscored: {failed}"
                if evals_data else "no evals were graded at all"
            )
            print(
                "[ERROR] Baseline grading did not produce a real score for "
                f"every eval ({detail}). A partial baseline cannot be compared "
                "against candidates, which are required to score the complete "
                "set. Re-run the baseline, or restrict --eval-ids to the evals "
                "that grade reliably. Aborting."
            )
            sys.exit(1)
        best_score = extract_score(bench)
        weaknesses = extract_weaknesses(bench)
        best_iteration = baseline_iter
        print(f"Baseline score: {best_score:.1%} (over all {len(evals_data)} evals)")
    else:
        print(f"[dry-run] Current description: {best_description}")
    print()

    # ── Optimization rounds ───────────────────────────────────────────────
    iter_counter = baseline_iter + 1

    for round_num in range(1, args.rounds + 1):
        print(f"═══ Round {round_num}/{args.rounds} ═══")
        print(f"Proposing {args.candidates} candidates (current best: {best_score:.1%}) ...")
        try:
            candidates = propose_candidates(
                best_description, best_score, weaknesses, args.candidates,
                eval_ids=args.eval_ids,
                max_budget_usd_per_call=args.max_grader_budget_usd_per_call,
                model=args.model,
                timeout_seconds=args.grader_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            print(f"[WARN] Candidate proposal timed out in round {round_num} — skipping round")
            print()
            continue
        for i, c in enumerate(candidates, 1):
            print(f"  [{i}] {c[:120]}...")

        if args.dry_run:
            print("[dry-run] skipping eval runs\n")
            continue

        round_best_score = best_score
        round_best_desc = best_description
        round_best_iter = best_iteration

        for i, candidate in enumerate(candidates, 1):
            iter_num = iter_counter
            iter_counter += 1
            print(f"\n  Candidate {i}/{len(candidates)}: {candidate[:80]}...")
            candidate_written = False
            try:
                try:
                    write_description(candidate)
                    candidate_written = True
                except ValueError as e:
                    # An over-length or angle-bracket candidate fails quick_validate.py.
                    # Skip it instead of crashing the whole optimization run.
                    print(f"  [WARN] Candidate {i} rejected ({e}) — skipping (not recorded).")
                    continue

                if not run_evals(
                    iter_num,
                    args.eval_ids,
                    max_budget_usd_per_call=args.max_budget_usd_per_call,
                    model=args.model,
                    timeout_seconds=args.output_timeout_seconds,
                ):
                    print(f"  [WARN] Eval run failed for candidate {i} — skipping (not recorded).")
                    continue

                bench = grade_evals(
                    iter_num,
                    args.eval_ids,
                    max_budget_usd_per_call=args.max_grader_budget_usd_per_call,
                    model=args.model,
                    timeout_seconds=args.grader_timeout_seconds,
                )
                if _is_infra_failure(bench):
                    print(f"  [WARN] Grading produced no real scores for candidate {i} — skipping (infrastructure failure, not recorded).")
                    continue

                score = extract_score(bench)
                w = extract_weaknesses(bench)
                history.append({
                    "round": round_num, "candidate": i, "iteration": iter_num,
                    "description": candidate, "score": score,
                })
                print(f"  Score: {score:.1%} {'*** NEW BEST ***' if score > round_best_score else ''}")
                if score > round_best_score:
                    round_best_score = score
                    round_best_desc = candidate
                    round_best_iter = iter_num
                    weaknesses = w
            finally:
                # A failed, interrupted, or rejected candidate must never remain
                # in the live SKILL.md. The round winner is applied only below.
                if candidate_written:
                    write_description(best_description)

        if round_best_score > best_score:
            best_score = round_best_score
            best_description = round_best_desc
            best_iteration = round_best_iter
            print(f"\n  Round {round_num} winner: {best_description[:100]}")
        else:
            print(f"\n  Round {round_num}: no improvement over {best_score:.1%}")

        write_description(best_description)
        print()

    # ── Final result ──────────────────────────────────────────────────────
    print("═══ Optimization Complete ═══")
    print(f"Original:  {original_description[:120]}...")
    print(f"Best:      {best_description[:120]}...")
    print(f"Score:     {best_score:.1%}")
    if best_description != original_description:
        print("\nUpdating SKILL.md with best description ...")
        write_description(best_description)
    else:
        print("\nOriginal description was already optimal — SKILL.md unchanged.")

    history_path = WORKSPACE / "loop-history.json"
    WORKSPACE.mkdir(exist_ok=True)
    history_path.write_text(json.dumps({
        "original_description": original_description,
        "best_description": best_description,
        "best_score": best_score,
        "history": history,
    }, indent=2))
    print(f"History saved: {history_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
