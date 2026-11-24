#!/usr/bin/env python3
"""
Grade CRO skill eval outputs against assertions from evals.json.

For each (eval, condition) output:
  - Reads the markdown output
  - Asks claude to score each assertion 0 or 1
  - Saves a grades JSON alongside the output

Then aggregates all grades into cro-workspace/iteration-N/benchmark.json.

Usage:
    python3 grade_evals.py --model EXACT_MODEL_ID
    python3 grade_evals.py --model EXACT_MODEL_ID --iteration 2
    python3 grade_evals.py --model EXACT_MODEL_ID --eval homepage-direct-audit
    python3 grade_evals.py --model EXACT_MODEL_ID --resume  # grade only missing/stale results

Every grader call runs with customizations and tools disabled, no session
persistence, an empty MCP configuration, and a per-call spending cap.
"""

from __future__ import annotations  # PEP 604 "X | None" annotations must work on Python 3.9

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from harness_config import (
    CONDITIONS,
    EVALS_JSON,
    GRADER_BUDGET_USD,
    GRADER_TIMEOUT_SECONDS,
    ISOLATED_CLAUDE_ARGS,
    REPO_ROOT,
    WORKSPACE,
    nonempty_model,
    positive_float,
    positive_int,
)
from run_evals import (
    BASELINE_SYSTEM,
    authenticated_output,
    build_skill_context,
    valid_output,
)

GRADER_SYSTEM = """\
You are an objective evaluator for AI-generated CRO (Conversion Rate Optimization) audit responses.
Your task is to score responses against specific assertions.

Rules:
- Score each assertion 1 (pass) or 0 (fail) — no partial credit
- Be strict: if the assertion says "must not use X" and X appears, score 0
- For negative cases, score 1 only if the response does NOT produce a CRO audit. Two sub-types:
  (a) routing negatives (a bare GA4/GSC lookup or a copy rewrite) — the response should name the skill it routes to (ga4 / google-search-console / marketing-voice);
  (b) decline negatives (a non-public URL such as localhost, no URL given, or an out-of-scope topic) — there is no skill to route to, so score 1 when the response declines / says the skill does not apply, without producing an audit.
  In both sub-types, producing an actual CRO audit (LIFT/PXL/report sections) scores 0.
- If the response is empty or starts with a harness failure sentinel ([ERROR / [TIMEOUT / [EXCEPTION / [EMPTY), score all assertions 0
- Output only valid JSON — no extra text, no markdown fencing
"""

GRADER_PROMPT_TEMPLATE = """\
Eval prompt (what the user asked):
"{prompt}"

Assertions to grade — score each against its DESCRIPTION, not just its id:
{assertion_list}

Response to grade:
---
{response}
---

Grade each assertion strictly (1=pass, 0=fail) against the matching description above. Output JSON exactly like this:
{{
  "scores": {{
    {assertion_schema}
  }},
  "notes": "one short sentence summarising what the response did right or wrong"
}}
"""


def validate_grade_payload(grades: object, assertions: list[dict]) -> dict | None:
    """Return a normalized grade only for an exact binary assertion map."""
    if not isinstance(grades, dict):
        return None
    scores = grades.get("scores")
    if not isinstance(scores, dict):
        return None
    expected_ids = [assertion["id"] for assertion in assertions]
    if set(scores) != set(expected_ids):
        return None
    if any(type(scores[assertion_id]) is not int  # bool is not a valid binary integer here
           or scores[assertion_id] not in (0, 1)
           for assertion_id in expected_ids):
        return None
    notes = grades.get("notes", "")
    if not isinstance(notes, str):
        return None
    return {
        "scores": {assertion_id: scores[assertion_id] for assertion_id in expected_ids},
        "notes": notes,
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assertions_sha256(assertions: list[dict]) -> str:
    encoded = json.dumps(
        assertions,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def grader_contract_sha256() -> str:
    """Fingerprint instructions and prompt shape that determine grading."""
    return hashlib.sha256(
        (GRADER_SYSTEM + "\n" + GRADER_PROMPT_TEMPLATE).encode("utf-8")
    ).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def grade_record(
    grades: dict,
    assertions: list[dict],
    output_path: Path,
    grader_model: str,
    eval_prompt: str,
) -> dict:
    """Bind cached grades to the output, rubric, grader contract, and model."""
    return {
        **grades,
        "_output_sha256": file_sha256(output_path),
        "_assertions_sha256": assertions_sha256(assertions),
        "_eval_prompt_sha256": text_sha256(eval_prompt),
        "_grader_contract_sha256": grader_contract_sha256(),
        "_grader_model": grader_model,
    }


def load_cached_grade(
    grades_path: Path,
    output_path: Path,
    assertions: list[dict],
    grader_model: str,
    eval_prompt: str,
) -> dict | None:
    """Return a grade only when all inputs to the grader still match."""
    if not grades_path.exists() or not valid_output(output_path):
        return None
    try:
        record = json.loads(grades_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("_output_sha256") != file_sha256(output_path):
        return None
    if record.get("_assertions_sha256") != assertions_sha256(assertions):
        return None
    if record.get("_eval_prompt_sha256") != text_sha256(eval_prompt):
        return None
    if record.get("_grader_contract_sha256") != grader_contract_sha256():
        return None
    if record.get("_grader_model") != grader_model:
        return None
    return validate_grade_payload(record, assertions)


def terminate_process_group(proc: subprocess.Popen) -> None:
    """Kill a grader process and every child it spawned."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def grade_one(
    eval_def: dict,
    output_path: Path,
    model: str,
    timeout: int = GRADER_TIMEOUT_SECONDS,
    max_budget_usd: float = GRADER_BUDGET_USD,
) -> dict | None:
    """Call claude to grade one output. Returns grades dict or None on error."""
    if not valid_output(output_path):
        print(f"    [SKIP] {output_path.name} has no valid output (harness failure sentinel) — not graded")
        return None
    response = output_path.read_text()

    assertions = eval_def["assertions"]
    # The grader needs each assertion's DESCRIPTION to score nuanced criteria
    # (e.g. voice-delegation, intent-vs-hero) — an id alone is not enough context.
    assertion_list = "\n".join(f'- {a["id"]}: {a["description"]}' for a in assertions)
    assertion_schema = ",\n    ".join(f'"{a["id"]}": 0_or_1' for a in assertions)

    prompt = GRADER_PROMPT_TEMPLATE.format(
        prompt=eval_def["prompt"],
        assertion_list=assertion_list,
        # A full nine-section CRO audit runs well past 8k chars; truncating
        # here would cut §8 (hypothesis docs) and §9 (engineering fixes) before
        # the grader sees them, spuriously failing end-of-report assertions.
        response=response[:40000],
        assertion_schema=assertion_schema,
    )

    cmd = [
        "claude", "-p",
        "--output-format", "text",
        *ISOLATED_CLAUDE_ARGS,
        "--model", model,
        "--max-budget-usd", str(max_budget_usd),
        "--append-system-prompt", GRADER_SYSTEM,
        prompt,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT),
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_process_group(proc)
            raise
        except KeyboardInterrupt:
            terminate_process_group(proc)
            raise
        if proc.returncode != 0:
            detail = stderr.strip() or stdout.strip() or "no diagnostic output"
            print(
                f"    [GRADE ERROR] {output_path.name}: Claude exited "
                f"{proc.returncode}: {detail[:300]}"
            )
            return None
        raw = stdout.strip()
        if not raw:
            print(
                f"    [GRADE ERROR] {output_path.name}: Claude exited 0 "
                "without a grade"
            )
            return None
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
        grades = json.loads(raw)
        validated = validate_grade_payload(grades, assertions)
        if validated is None:
            print(
                f"    [GRADE ERROR] {output_path.name}: grader returned a "
                "non-binary, missing, or extra assertion score"
            )
        return validated
    except Exception as e:
        print(f"    [GRADE ERROR] {output_path.name}: {e}")
        return None


def aggregate(all_grades: dict, evals: list) -> dict:
    """Build benchmark.json structure from raw grades."""
    benchmark = {"evals": {}}

    for eval_def in evals:
        eval_id = eval_def["id"]
        assertions = eval_def["assertions"]
        total_weight = sum(a["weight"] for a in assertions)
        eval_result = {"prompt": eval_def["prompt"], "conditions": {}, "assertions": assertions}

        for cond in CONDITIONS:
            grades = all_grades.get(eval_id, {}).get(cond)
            grades = validate_grade_payload(grades, assertions)
            if grades is None:
                eval_result["conditions"][cond] = {"score": None, "notes": "grading failed", "raw": {}}
                continue

            scores = grades.get("scores", {})
            weighted_score = sum(
                scores.get(a["id"], 0) * a["weight"] for a in assertions
            )
            pct = round(weighted_score / total_weight, 3) if total_weight else 0

            eval_result["conditions"][cond] = {
                "score": pct,
                "weighted_score": weighted_score,
                "total_weight": total_weight,
                "notes": grades.get("notes", ""),
                "raw": scores,
            }

        benchmark["evals"][eval_id] = eval_result

    summary = {}
    for cond in CONDITIONS:
        scores = [
            benchmark["evals"][eid]["conditions"][cond]["score"]
            for eid in benchmark["evals"]
        ]
        scores = [s for s in scores if s is not None]
        summary[cond] = round(sum(scores) / len(scores), 3) if scores else None

    benchmark["summary"] = summary
    benchmark["delta"] = {}
    if summary.get("with-skill") is not None and summary.get("baseline") is not None:
        benchmark["delta"]["with_skill_vs_baseline"] = round(summary["with-skill"] - summary["baseline"], 3)

    return benchmark


def collect_cached_grades(
    evals: list[dict],
    iteration_dir: Path,
    grader_model: str,
    skill_context: str,
) -> dict:
    """Load every still-authenticated grade record for a benchmark rebuild."""
    collected: dict[str, dict[str, dict | None]] = {}
    for eval_def in evals:
        eval_id = eval_def["id"]
        eval_dir = iteration_dir / eval_id
        collected[eval_id] = {}
        for cond in CONDITIONS:
            output_path = eval_dir / f"{cond}.md"
            system_prompt = (
                skill_context if cond == "with-skill" else BASELINE_SYSTEM
            )
            if authenticated_output(
                output_path,
                eval_def["prompt"],
                system_prompt,
            ) is None:
                collected[eval_id][cond] = None
            else:
                collected[eval_id][cond] = load_cached_grade(
                    eval_dir / f"{cond}.grades.json",
                    output_path,
                    eval_def["assertions"],
                    grader_model,
                    eval_def["prompt"],
                )
    return collected


def authenticated_output_models(
    evals: list[dict],
    iteration_dir: Path,
    skill_context: str,
) -> set[str]:
    """Return producer models for outputs valid under the current eval inputs."""
    models: set[str] = set()
    for eval_def in evals:
        eval_dir = iteration_dir / eval_def["id"]
        for cond in CONDITIONS:
            metadata = authenticated_output(
                eval_dir / f"{cond}.md",
                eval_def["prompt"],
                skill_context if cond == "with-skill" else BASELINE_SYSTEM,
            )
            if metadata is not None:
                models.add(metadata["model"])
    return models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=positive_int, default=1)
    parser.add_argument("--eval", help="Grade one eval only")
    parser.add_argument("--eval-ids", help="Comma-separated list of eval IDs to grade (alternative to --eval)")
    parser.add_argument(
        "--model",
        type=nonempty_model,
        required=True,
        help="Exact Claude model ID to pin for every paid grader call",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=positive_int,
        default=GRADER_TIMEOUT_SECONDS,
        help="Per-grader-call timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse grades only when their output bytes and assertions still match",
    )
    parser.add_argument(
        "--max-budget-usd-per-call",
        type=positive_float,
        default=GRADER_BUDGET_USD,
        help="Hard Claude CLI budget cap for each grader call (default: 0.5)",
    )
    parser.add_argument(
        "--max-model-calls",
        type=positive_int,
        default=100,
        help="Refuse a run whose planned grader-call count exceeds this value (default: 100)",
    )
    args = parser.parse_args()

    evals = json.loads(EVALS_JSON.read_text())
    if args.eval_ids:
        requested = [s.strip() for s in args.eval_ids.split(",") if s.strip()]
        available = {e["id"] for e in evals}
        missing = [i for i in requested if i not in available]
        if missing:
            print(f"Error: eval(s) not found in evals.json: {missing}")
            sys.exit(1)
        evals = [e for e in evals if e["id"] in requested]
    elif args.eval:
        evals = [e for e in evals if e["id"] == args.eval]
        if not evals:
            print(f"Error: eval '{args.eval}' not found in evals.json")
            sys.exit(1)

    iteration_dir = WORKSPACE / f"iteration-{args.iteration}"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    skill_context = build_skill_context()

    # A single benchmark must never compare responses produced by different
    # models. Per-file metadata already binds each output to its request; this
    # cross-file guard prevents a subset rerun from creating a mixed iteration.
    all_evals = json.loads(EVALS_JSON.read_text())
    output_models = authenticated_output_models(
        all_evals,
        iteration_dir,
        skill_context,
    )
    if len(output_models) > 1:
        print(
            "Error: this iteration contains authenticated outputs from multiple "
            f"models: {sorted(output_models)}. Use a new iteration or rerun all "
            "outputs with one model before grading."
        )
        sys.exit(2)

    planned_calls = 0
    for eval_def in evals:
        for cond in CONDITIONS:
            output_path = iteration_dir / eval_def["id"] / f"{cond}.md"
            grades_path = iteration_dir / eval_def["id"] / f"{cond}.grades.json"
            system_prompt = (
                skill_context if cond == "with-skill" else BASELINE_SYSTEM
            )
            output_is_authenticated = authenticated_output(
                output_path,
                eval_def["prompt"],
                system_prompt,
            ) is not None
            cached = (
                load_cached_grade(
                    grades_path,
                    output_path,
                    eval_def["assertions"],
                    args.model,
                    eval_def["prompt"],
                )
                if args.resume
                else None
            )
            if output_is_authenticated and cached is None:
                planned_calls += 1
    if planned_calls > args.max_model_calls:
        print(
            f"Error: this run plans {planned_calls} grader calls, above "
            f"--max-model-calls {args.max_model_calls}. Raise the cap explicitly to continue."
        )
        sys.exit(2)

    print(f"\nGrading outputs in {iteration_dir.relative_to(REPO_ROOT)}\n")

    all_grades = {}
    for eval_def in evals:
        eval_id = eval_def["id"]
        eval_dir = iteration_dir / eval_id
        all_grades[eval_id] = {}

        for cond in CONDITIONS:
            output_path = eval_dir / f"{cond}.md"
            grades_path = eval_dir / f"{cond}.grades.json"
            print(f"  Grading {eval_id} / {cond} ...")
            system_prompt = (
                skill_context if cond == "with-skill" else BASELINE_SYSTEM
            )
            output_is_authenticated = authenticated_output(
                output_path,
                eval_def["prompt"],
                system_prompt,
            ) is not None
            if not output_is_authenticated:
                grades_path.unlink(missing_ok=True)
                all_grades[eval_id][cond] = None
                print(
                    f"    [SKIP] {output_path.name} is missing, failed, or "
                    "does not match its current prompt/context metadata"
                )
                continue
            grades = (
                load_cached_grade(
                    grades_path,
                    output_path,
                    eval_def["assertions"],
                    args.model,
                    eval_def["prompt"],
                )
                if args.resume
                else None
            )
            if grades is not None:
                print(f"    [SKIP] {grades_path.name} matches output and assertions")
            else:
                grades_path.unlink(missing_ok=True)
                grades = grade_one(
                    eval_def,
                    output_path,
                    model=args.model,
                    timeout=args.timeout_seconds,
                    max_budget_usd=args.max_budget_usd_per_call,
                )
            all_grades[eval_id][cond] = grades

            if grades:
                grades_path.write_text(json.dumps(
                    grade_record(
                        grades,
                        eval_def["assertions"],
                        output_path,
                        args.model,
                        eval_def["prompt"],
                    ),
                    indent=2,
                ))
                scores = grades.get("scores", {})
                assertions = eval_def["assertions"]
                total_weight = sum(a["weight"] for a in assertions)
                weighted = sum(scores.get(a["id"], 0) * a["weight"] for a in assertions)
                # Format the ratio directly — do NOT round before scaling to a
                # percent. `round(x, 1) * 100` quantises every score to the
                # nearest 10% (5/6 printed as 80%, 7/8 as 90%), which disagrees
                # with the 3-dp score aggregate() writes to benchmark.json.
                pct = weighted / total_weight if total_weight else 0
                print(f"    Score: {weighted}/{total_weight} ({pct:.0%}) — {grades.get('notes', '')[:80]}")

    print("\nAggregating into benchmark.json ...")

    existing_bench = iteration_dir / "benchmark.json"
    preserve_iteration = args.resume or existing_bench.exists()
    if preserve_iteration:
        aggregate_evals = all_evals
    elif args.eval_ids:
        requested_ids = {s.strip() for s in args.eval_ids.split(",") if s.strip()}
        aggregate_evals = [e for e in all_evals if e["id"] in requested_ids]
    elif args.eval:
        aggregate_evals = [e for e in all_evals if e["id"] == args.eval]
    else:
        aggregate_evals = all_evals

    # Rebuild from authenticated per-output grade records, never by merging
    # benchmark.json. A subset retry therefore preserves every unchanged grade
    # whose output bytes and assertions still match, while stale or missing
    # records become explicit None scores rather than silently surviving.
    aggregate_grades = collect_cached_grades(
        aggregate_evals,
        iteration_dir,
        args.model,
        skill_context,
    )
    benchmark = aggregate(aggregate_grades, aggregate_evals)
    benchmark["provenance"] = {
        "output_model": next(iter(output_models), None),
        "grader_model": args.model,
    }
    existing_bench.write_text(json.dumps(benchmark, indent=2))

    print(f"\nBenchmark saved: {existing_bench.relative_to(REPO_ROOT)}")
    print(f"\nSummary:")
    for cond, score in benchmark["summary"].items():
        label = f"{cond:15s}"
        val = f"{score:.1%}" if score is not None else "N/A"
        print(f"  {label} {val}")
    if "with_skill_vs_baseline" in benchmark.get("delta", {}):
        delta = benchmark["delta"]["with_skill_vs_baseline"]
        sign = "+" if delta >= 0 else ""
        print(f"\n  Skill lift: {sign}{delta:.1%}")


if __name__ == "__main__":
    main()
