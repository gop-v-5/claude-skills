#!/usr/bin/env python3
"""
CRO skill eval runner.

Runs each prompt in evals.json against the claude CLI in two conditions:
  - with-skill: the complete CRO skill context injected as system prompt
  - baseline: bare prompt, no skill context

Usage:
    python3 run_evals.py --model EXACT_MODEL_ID
    python3 run_evals.py --model EXACT_MODEL_ID --iteration 2
    python3 run_evals.py --model EXACT_MODEL_ID --eval homepage-direct-audit
    python3 run_evals.py --model EXACT_MODEL_ID --condition with-skill
    python3 run_evals.py --model EXACT_MODEL_ID --resume  # retry only missing/failed outputs

Every Claude call runs with customizations and tools disabled, no session
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
import time
from pathlib import Path

from harness_config import (
    CONDITIONS,
    EVALS_JSON,
    ISOLATED_CLAUDE_ARGS,
    OUTPUT_BUDGET_USD,
    OUTPUT_TIMEOUT_SECONDS,
    REPO_ROOT,
    SKILL_DIR,
    SKILL_MD,
    WORKSPACE,
    nonempty_model,
    positive_float,
    positive_int,
)

# Prefixes run_claude() writes to an output file when a run fails instead of
# producing a real audit. grade_evals.py imports this tuple for its skip guard,
# so the producer (here) and the consumer (there) can't drift apart — every
# failure write below MUST begin with one of these prefixes.
FAILURE_SENTINELS = ("[ERROR", "[TIMEOUT", "[EXCEPTION", "[EMPTY")

SYSTEM_PROMPT_PREAMBLE = """\
You are a Conversion Rate Optimization (CRO) analyst. You follow the CRO skill documentation
injected below precisely — including its own rules about which requests it does and does not
handle, how it obtains data it does not have, and what its output must contain. Do not assume
the request in front of you is one the skill should act on: that is the documentation's call to
make, not this preamble's.

This preamble deliberately restates none of those rules. The scope boundaries, the routing
targets, the delegation mechanism, the report structure, and the rules about unavailable data
are the very things the evals exist to test. Anything spelled out here would be answered by the
preamble instead of by the skill, and the eval would stop measuring the skill.

IMPORTANT — the eval environment. This constrains HOW you respond, never WHETHER to respond.
This session has no live data access, no connected integrations of any kind, and no other
invocable skills: nothing can be fetched, queried, or called, and you can only write. So where
the documentation's workflow would reach for something unreachable here, say what you would do
and continue on that basis rather than stopping. Respond at the depth and structure the
documentation specifies rather than summarising, and write as if presenting to the marketing team.

"""

BASELINE_SYSTEM = """\
You are a Conversion Rate Optimization consultant. A user will share a landing-page URL and a
CRO-flavored request (audit, test ideas, LIFT review, hypothesis docs, or funnel drop-off).

Answer with general CRO best practices. You have no live analytics data in this session —
describe what you would analyze, what you would look at on the page, and what the likely
conversion issues and test ideas are. Do not invent specific metrics.
"""


def build_skill_context() -> str:
    """Concatenate SKILL.md plus the reference rubrics and report template the
    workflow actually loads, so evals exercise the real files — not just
    SKILL.md. Without these, an eval can pass while a stale or broken
    lift-model / pxl / hypothesis / report-template / page-profile file goes
    unnoticed.

    Every reference SKILL.md tells the workflow to load must be listed here.
    Step 8 loads page-profile-schema.md, so omitting it would let a profile
    eval "pass" against a schema the model never actually saw.
    """
    files = [
        ("SKILL.md", SKILL_MD),
        ("references/lift-model.md", SKILL_DIR / "references" / "lift-model.md"),
        ("references/pxl-prioritization.md", SKILL_DIR / "references" / "pxl-prioritization.md"),
        ("references/hypothesis-template.md", SKILL_DIR / "references" / "hypothesis-template.md"),
        ("references/audience-context.md", SKILL_DIR / "references" / "audience-context.md"),
        ("references/page-profile-schema.md", SKILL_DIR / "references" / "page-profile-schema.md"),
        ("assets/report-template.md", SKILL_DIR / "assets" / "report-template.md"),
    ]
    missing = [label for label, path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "CRO eval context is incomplete; missing required file(s): "
            + ", ".join(missing)
        )

    parts = [SYSTEM_PROMPT_PREAMBLE]
    for label, path in files:
        parts.append(f"--- {label} ---\n")
        parts.append(path.read_text())
    return "\n".join(parts)


def terminate_process_group(proc: subprocess.Popen) -> None:
    """Kill a model process and every child it spawned."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def valid_output(path: Path) -> bool:
    """True only when *path* contains a gradeable model response."""
    if not path.exists():
        return False
    try:
        output = path.read_text()
    except (OSError, UnicodeError):
        return False
    return bool(output.strip()) and not output.startswith(FAILURE_SENTINELS)


def output_metadata_path(output_path: Path) -> Path:
    return output_path.with_suffix(".meta.json")


def request_sha256(prompt: str, system_prompt: str | None, model: str) -> str:
    """Fingerprint every input whose change requires a fresh model response."""
    encoded = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "system_prompt": system_prompt,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_output_metadata(
    output_path: Path,
    prompt: str,
    system_prompt: str | None,
    model: str,
) -> None:
    output_metadata_path(output_path).write_text(json.dumps(
        {
            "model": model,
            "request_sha256": request_sha256(prompt, system_prompt, model),
            "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        },
        indent=2,
    ))


def authenticated_output(
    output_path: Path,
    prompt: str,
    system_prompt: str | None,
    expected_model: str | None = None,
) -> dict | None:
    """Return output metadata only when bytes and the full request agree.

    ``expected_model`` is optional so the grader can discover the producer
    model from metadata while still authenticating the prompt and system
    context. The runner supplies it when deciding whether ``--resume`` is safe.
    """
    metadata_path = output_metadata_path(output_path)
    if not valid_output(output_path) or not metadata_path.exists():
        return None
    try:
        metadata = json.loads(metadata_path.read_text())
        output_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    except (json.JSONDecodeError, OSError, UnicodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    model = metadata.get("model")
    if not isinstance(model, str) or not model.strip():
        return None
    if expected_model is not None and model != expected_model:
        return None
    if metadata.get("request_sha256") != request_sha256(
        prompt, system_prompt, model
    ):
        return None
    if metadata.get("output_sha256") != output_hash:
        return None
    return metadata


def resumable_output(
    output_path: Path,
    prompt: str,
    system_prompt: str | None,
    model: str,
) -> bool:
    """Reuse output only when its bytes and complete request still match."""
    return authenticated_output(
        output_path,
        prompt,
        system_prompt,
        expected_model=model,
    ) is not None


def run_claude(
    prompt: str,
    system_prompt: str | None,
    output_path: Path,
    model: str,
    timeout: int = OUTPUT_TIMEOUT_SECONDS,
    max_budget_usd: float = OUTPUT_BUDGET_USD,
) -> bool:
    """Run claude -p with optional system prompt, save output to output_path.

    Uses Popen with start_new_session=True so the child process gets its own
    process group. On timeout, kills the entire group with SIGKILL — plain
    subprocess.run only kills the parent pid, which lets claude-cli's child
    processes (Node, MCP servers) survive and burn 10+ minutes past the
    timeout.
    """
    metadata_path = output_metadata_path(output_path)
    metadata_path.unlink(missing_ok=True)
    cmd = [
        "claude", "-p", "--output-format", "text",
        *ISOLATED_CLAUDE_ARGS,
        "--model", model,
        "--max-budget-usd", str(max_budget_usd),
    ]
    if system_prompt:
        cmd += ["--append-system-prompt", system_prompt]
    cmd.append(prompt)

    print(f"  Running: {' '.join(cmd[:4])} ... [{output_path.name}]")
    t0 = time.time()

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
            output_path.write_text(f"[TIMEOUT after {timeout}s]")
            print(f"  [TIMEOUT] {output_path.relative_to(REPO_ROOT)} ({time.time() - t0:.1f}s)")
            return False
        except KeyboardInterrupt:
            terminate_process_group(proc)
            raise
        elapsed = time.time() - t0
        if proc.returncode == 0 and not stdout.strip():
            output_path.write_text("[EMPTY OUTPUT]")
            print(
                f"  [EMPTY] {output_path.relative_to(REPO_ROOT)} "
                f"({elapsed:.1f}s) — no gradeable response"
            )
            return False
        output = stdout if proc.returncode == 0 else f"[ERROR exitcode={proc.returncode}]\n{stderr}"
        output_path.write_text(output)
        if proc.returncode == 0:
            write_output_metadata(output_path, prompt, system_prompt, model)
        status = "OK" if proc.returncode == 0 else "FAIL"
        print(f"  [{status}] {output_path.relative_to(REPO_ROOT)} ({elapsed:.1f}s)")
        return proc.returncode == 0
    except Exception as e:
        output_path.write_text(f"[EXCEPTION: {e}]")
        print(f"  [EXCEPTION] {output_path.relative_to(REPO_ROOT)}: {e}")
        return False


def run_eval(
    eval_def: dict,
    iteration_dir: Path,
    condition: str | None,
    skill_context: str,
    max_budget_usd: float,
    model: str,
    timeout: int,
    resume: bool = False,
) -> dict:
    """Run a single eval in one or both conditions. Returns {condition: success}."""
    eval_id = eval_def["id"]
    prompt = eval_def["prompt"]
    eval_dir = iteration_dir / eval_id
    eval_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    conditions = [condition] if condition else CONDITIONS

    for cond in conditions:
        out_path = eval_dir / f"{cond}.md"
        system_prompt = skill_context if cond == "with-skill" else BASELINE_SYSTEM
        if resume and resumable_output(out_path, prompt, system_prompt, model):
            print(
                f"  [SKIP] {out_path.relative_to(REPO_ROOT)} "
                "matches model, prompt, context, and output hash"
            )
            results[cond] = True
            continue
        ok = run_claude(
            prompt,
            system_prompt,
            out_path,
            model=model,
            timeout=timeout,
            max_budget_usd=max_budget_usd,
        )
        results[cond] = ok

    return results


def main():
    parser = argparse.ArgumentParser(description="Run CRO skill evals")
    parser.add_argument(
        "--iteration",
        type=positive_int,
        default=1,
        help="Iteration number (default: 1)",
    )
    parser.add_argument("--eval", help="Run a specific eval by ID only")
    parser.add_argument("--eval-ids", help="Comma-separated list of eval IDs to run (alternative to --eval)")
    parser.add_argument("--condition", choices=["with-skill", "baseline"], help="Run one condition only")
    parser.add_argument(
        "--model",
        type=nonempty_model,
        required=True,
        help="Exact Claude model ID to pin for every paid output call",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=positive_int,
        default=OUTPUT_TIMEOUT_SECONDS,
        help="Per-output-call timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse valid existing outputs and rerun only missing or failed ones",
    )
    parser.add_argument(
        "--max-budget-usd-per-call",
        type=positive_float,
        default=OUTPUT_BUDGET_USD,
        help="Hard Claude CLI budget cap for each model call (default: 2.0)",
    )
    parser.add_argument(
        "--max-model-calls",
        type=positive_int,
        default=100,
        help="Refuse a run whose planned model-call count exceeds this value (default: 100)",
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

    print(f"\nBuilding skill context from SKILL.md ...")
    skill_context = build_skill_context()
    print(f"Skill context: {len(skill_context)} chars\n")

    selected_conditions = [args.condition] if args.condition else CONDITIONS
    iteration_dir = WORKSPACE / f"iteration-{args.iteration}"
    planned_calls = sum(
        1
        for eval_def in evals
        for cond in selected_conditions
        if (
            not args.resume
            or not resumable_output(
                iteration_dir / eval_def["id"] / f"{cond}.md",
                eval_def["prompt"],
                skill_context if cond == "with-skill" else BASELINE_SYSTEM,
                args.model,
            )
        )
    )
    if planned_calls > args.max_model_calls:
        print(
            f"Error: this run plans {planned_calls} model calls, above "
            f"--max-model-calls {args.max_model_calls}. Raise the cap explicitly to continue."
        )
        sys.exit(2)

    iteration_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(evals)} eval(s) × {'1 condition' if args.condition else '2 conditions'} → {iteration_dir.relative_to(REPO_ROOT)}\n")

    all_results = {}
    any_failed = False
    for eval_def in evals:
        print(f"── Eval: {eval_def['id']} ──")
        results = run_eval(
            eval_def,
            iteration_dir,
            args.condition,
            skill_context,
            args.max_budget_usd_per_call,
            args.model,
            args.timeout_seconds,
            args.resume,
        )
        all_results[eval_def["id"]] = results
        if not all(results.values()):
            any_failed = True
        print()

    print("Done.")
    for eval_id, res in all_results.items():
        for cond, ok in res.items():
            icon = "✓" if ok else "✗"
            print(f"  {icon}  {eval_id} / {cond}")

    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
