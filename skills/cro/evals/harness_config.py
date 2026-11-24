#!/usr/bin/env python3
"""Shared filesystem and process settings for the CRO eval harness.

All harness entry points import this module. Keeping path discovery and Claude
CLI isolation here prevents the runner, grader, and optimization loop from
silently operating on different workspaces.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def resolve_project_root(skill_dir: Path) -> Path:
    """Return the containing Git checkout, or the loose skill's parent.

    A repository install normally lives at ``<repo>/skills/cro``. A developer
    may also run a standalone copy at ``<working-dir>/cro``. Counting a fixed
    number of parents works only for the first layout and previously sent a
    standalone copy's results to ``~/cro-workspace``. Walking to the nearest
    Git root keeps repository installs stable; the fallback keeps standalone
    state beside the working directory that owns the copy.
    """
    resolved = skill_dir.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            return candidate
    return resolved.parent


SKILL_DIR = Path(__file__).resolve().parents[1]
EVALS_DIR = SKILL_DIR / "evals"
PROJECT_ROOT = resolve_project_root(SKILL_DIR)

# Compatibility name retained for the existing harness API and tests.
REPO_ROOT = PROJECT_ROOT
SKILL_MD = SKILL_DIR / "SKILL.md"
EVALS_JSON = EVALS_DIR / "evals.json"
WORKSPACE = PROJECT_ROOT / "cro-workspace"

CONDITIONS = ("with-skill", "baseline")
OUTPUT_TIMEOUT_SECONDS = 600
GRADER_TIMEOUT_SECONDS = 180
OUTPUT_BUDGET_USD = 2.0
GRADER_BUDGET_USD = 0.5

ISOLATED_CLAUDE_ARGS = (
    "--safe-mode",
    "--tools", "",
    "--no-session-persistence",
    "--strict-mcp-config",
    "--mcp-config", '{"mcpServers":{}}',
)


def positive_int(value: str) -> int:
    """Argparse type for strictly positive integer controls."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def positive_float(value: str) -> float:
    """Argparse type for strictly positive numeric controls."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def nonempty_model(value: str) -> str:
    """Argparse type that prevents an empty/whitespace model identifier."""
    parsed = value.strip()
    if not parsed:
        raise argparse.ArgumentTypeError("must be a non-empty model ID")
    return parsed
