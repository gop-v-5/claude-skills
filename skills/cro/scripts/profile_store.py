#!/usr/bin/env python3
"""Crash-safe, conflict-detecting, semantically-validated writes for CRO page profiles.

The audit still owns schema construction and merge decisions. This helper owns
the invariants that prose cannot guarantee:

- canonical writes are serialized, compare the file fingerprint observed
  before the merge, and replace atomically;
- a canonical profile written by a NEWER schema is never downgraded — the
  version is re-read under the lock, not trusted from the audit's own read;
- recovery writes use exclusive creation, so two runs can never claim the same
  timestamped path or overwrite one another;
- semantically invalid payloads never reach the profile store, on either path.

The validation here is deliberately total: a payload that would corrupt a future
comparison (a fabricated status, a subtotal that disagrees with its criteria, a
resolved issue whose check never ran) is rejected before it can be persisted.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MISSING = "MISSING"
RECOVERY_KINDS = {"corrupt", "unsupported-version"}

# Bumped from 1.0 when latest.engineering_checks_run and
# engineering_issues[].check_id were added. See "schema_version" in
# references/page-profile-schema.md for the 1.0 -> 1.1 migration.
SCHEMA_VERSION = "1.1"
SUPPORTED_LEGACY_VERSIONS = {"1.0"}
VERSION_RE = re.compile(r"^\d+\.\d+$")
AUDIT_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-\d+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CHECK_ID_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"
SHOPIFY_HOST = "apps.shopify.com"
# A Shopify App Store listing is exactly one path segment: /<app-handle>.
SHOPIFY_LISTING_PATH_RE = re.compile(r"^/[a-z0-9][a-z0-9-]*$")
# A public DNS name: dot-separated labels, at least two, letters/digits/hyphens,
# no label starting or ending with a hyphen, alphabetic top-level label.
HOST_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def is_public_hostname(host: str) -> bool:
    labels = host.lower().split(".")
    return (len(labels) >= 2
            and all(HOST_LABEL_RE.match(label) for label in labels)
            and labels[-1].isalpha())

STATUSES = {
    "proposed", "ready", "blocked_by_engineering", "needs_data",
    "running", "won", "lost", "inconclusive", "shipped", "abandoned",
}
SKILL_SETTABLE = {"proposed", "ready", "blocked_by_engineering", "needs_data"}
ELEMENT_TYPES = {"headline", "subheadline", "cta", "microcopy", "layout"}
SEVERITIES = {"Sev0", "Sev1", "Sev2"}
MODES = {"full_data", "partial_data", "heuristic_only"}
BLOCKS = ("page_snapshot", "metrics", "lift", "pxl")
LIFT_FACTORS = ("value_proposition", "clarity", "relevance",
                "distraction", "urgency", "anxiety")
PXL_POINTS = {
    "potential": {"above_fold": 1, "noticeable_5s": 1, "added_or_removed": 1,
                  "high_traffic": 2, "known_conversion_problem": 1},
    "importance": {"top5_traffic": 2, "top5_conversion_value": 2, "must_interact": 1},
    "ease": {"no_dev_time": 1, "ships_this_sprint": 1, "no_third_party": 1},
    "evidence": {"qualitative": 1, "quantitative": 1},
}
PXL_MAX = sum(sum(g.values()) for g in PXL_POINTS.values())
DELTA_BLOCKS = ("metrics", "lift", "pxl")
ROLLUP_FIELDS = {
    "compared_to", "compared_against", "not_compared", "comparable",
    "comparability_note", "lift_total_delta", "lift_deltas", "metric_deltas",
    "new_experiments", "recurring_experiments", "dropped_experiments",
    "rank_changes", "new_issues", "resolved_issues",
}


class ProfileConflictError(RuntimeError):
    """The canonical profile changed after the audit read it."""


class ProfileVersionError(RuntimeError):
    """The canonical profile cannot be safely replaced by this writer."""


class ProfileInvalidError(ValueError):
    """The payload is not a valid profile. Carries every problem found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


def version_tuple(value: str) -> tuple[int, int]:
    major, minor = value.split(".")
    return int(major), int(minor)


def tier(score: int) -> str:
    return "P0" if score >= 13 else "P1" if score >= 9 else "P2" if score >= 5 else "P3"


def is_int(value: Any) -> bool:
    """True only for a real integer.

    `bool` subclasses `int` and `True == 1`, so every plain isinstance/`!=`
    integer check accepts a boolean and lets it persist to disk as JSON `true`
    while the surrounding arithmetic still balances. This is the same collapse
    the identity test in check_pxl prevents for criteria; these are the fields
    that test never covered.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: Any) -> bool:
    """True for a JSON number, excluding booleans."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def exact_json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int/float equality collapse."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (
            left.keys() == right.keys()
            and all(exact_json_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list):
        return (
            len(left) == len(right)
            and all(exact_json_equal(a, b) for a, b in zip(left, right))
        )
    return left == right


def non_finite_numbers(value: Any, path: str = "payload") -> list[str]:
    """Return paths to floats JSON cannot encode (NaN and infinities)."""
    found: list[str] = []
    if type(value) is float and not math.isfinite(value):
        found.append(path)
    elif isinstance(value, dict):
        for key, child in value.items():
            found.extend(non_finite_numbers(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(non_finite_numbers(child, f"{path}[{index}]"))
    return found


def parse_audit_id(value: Any) -> tuple[dt.date, int] | None:
    """Parse a real audit date and its same-day ordinal.

    The unsuffixed ID is the first audit of a day. A collision starts at ``-2``;
    accepting ``-0`` or ``-1`` would create a second spelling for an existing
    ordering position.
    """
    if not isinstance(value, str):
        return None
    match = AUDIT_ID_RE.fullmatch(value)
    if not match:
        return None
    date_text = value[:10]
    try:
        audit_date = dt.date.fromisoformat(date_text)
    except ValueError:
        return None
    suffix = match.group(1)
    ordinal = int(suffix[1:]) if suffix else 1
    if suffix and ordinal < 2:
        return None
    return audit_date, ordinal


def is_valid_audit_id(value: Any) -> bool:
    return parse_audit_id(value) is not None


def parse_date(value: Any) -> dt.date | None:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def assert_not_future(payload: Any, today: dt.date | None = None) -> None:
    """Reject a profile whose newest audit is later than the writer's clock."""
    latest = payload.get("latest") if isinstance(payload, dict) else None
    audit_id = latest.get("audit_id") if isinstance(latest, dict) else None
    parsed = parse_audit_id(audit_id)
    if parsed is None:
        return  # validate_profile reports the format problem
    limit = today or dt.date.today()
    if parsed[0] > limit:
        raise ProfileInvalidError([
            "latest.audit_id: "
            f"{audit_id!r} is later than today's date {limit.isoformat()!r}; "
            "a future canonical audit would make the next real audit chronologically older"
        ])


def normalized_page_path(value: str) -> str:
    return (value or "/").rstrip("/") or "/"


def audit_sort_key(value: str) -> tuple[dt.date, int]:
    """Sort YYYY-MM-DD[-N] audit ids chronologically, including same-day suffixes."""
    parsed = parse_audit_id(value)
    if parsed is None:
        raise ValueError(f"invalid audit id: {value!r}")
    return parsed


def derive_slug(host: Any, path: Any) -> str:
    """The documented slug rule, applied in order.

    A root path becomes `/home` *before* slugifying — keeping the leading
    slash, so the `home` marker stays separated from the host and the rule
    yields the documented `www-example-com-home` rather than
    `www-example-comhome`. Query strings and fragments are dropped.
    """
    if not isinstance(host, str) or not isinstance(path, str):
        return ""
    path = path.split("?")[0].split("#")[0]
    if path in ("", "/"):
        path = "/home"
    elif not path.startswith("/"):
        path = "/" + path
    return re.sub(r"[^a-z0-9]+", "-", (host + path).lower()).strip("-")


def assert_payload_matches_target(canonical: Path, payload: Any) -> None:
    """Refuse to file a profile outside its store or under a slug that is not its own.

    `page.slug` names the file this profile lives in, so a payload written to
    any other path silently overwrites a DIFFERENT page's history and reports
    success — the fingerprint guard cannot catch it, because it is MISSING on a
    first write and correctly matches the victim on a second. Documented in the
    Write algorithm and, until now, checked nowhere.
    """
    if canonical.parent.resolve() != PROFILE_DIR.resolve():
        raise ProfileInvalidError([
            f"canonical directory {str(canonical.parent)!r} is not this skill's "
            f"profile store {str(PROFILE_DIR)!r}"
        ])
    if not isinstance(payload, dict) or not isinstance(payload.get("page"), dict):
        return  # validate_profile reports the real structural problem
    slug = payload["page"].get("slug")
    if not isinstance(slug, str) or not slug:
        raise ProfileInvalidError([
            "page.slug must be a non-empty string before a profile path can be bound"
        ])
    expected_name = f"{slug}.json"
    if canonical.name != expected_name:
        raise ProfileInvalidError([
            f"page.slug {slug!r} requires canonical file {expected_name!r}, not "
            f"{canonical.name!r} — "
            "writing it here would overwrite a different page's profile"
        ])


# ── validation ────────────────────────────────────────────────────────────────

class _Validator:
    """Collects every problem rather than raising on the first one."""

    def __init__(self, payload: Any, mode: str) -> None:
        self.p = payload
        self.mode = mode  # "canonical" | "recovery"
        self.problems: list[str] = []

    def fail(self, where: str, what: str) -> None:
        self.problems.append(f"{where}: {what}")

    def need(self, obj: Any, where: str, keys: tuple[str, ...]) -> bool:
        if not isinstance(obj, dict):
            self.fail(where, "must be an object")
            return False
        missing = [k for k in keys if k not in obj]
        if missing:
            self.fail(where, f"missing required key(s) {missing}")
        return not missing

    def enum(self, value: Any, where: str, allowed: set, nullable: bool = False) -> None:
        if value is None and nullable:
            return
        try:
            valid = value in allowed
        except TypeError:
            valid = False
        if not valid:
            self.fail(where, f"{value!r} is not one of {sorted(allowed)}")

    # -- top level ------------------------------------------------------------

    def run(self) -> list[str]:
        if not isinstance(self.p, dict):
            return ["payload: must be a JSON object"]
        for path in non_finite_numbers(self.p):
            self.fail(path, "must be a finite JSON number, never NaN or Infinity")
        if not self.need(self.p, "payload",
                         ("schema_version", "page", "latest",
                          "history", "experiments", "engineering_issues")):
            return self.problems

        version = self.p["schema_version"]
        if not isinstance(version, str) or not VERSION_RE.match(version):
            self.fail("schema_version", f"{version!r} must look like '<major>.<minor>'")
        elif version != SCHEMA_VERSION:
            self.fail("schema_version",
                      f"{version!r} — this writer emits {SCHEMA_VERSION!r}; "
                      "migrate the payload before writing")

        for key in ("history", "experiments", "engineering_issues"):
            if not isinstance(self.p[key], list):
                self.fail(key, "must be an array")

        self.check_page()
        self.check_latest()
        self.check_history()
        self.check_experiments()
        self.check_issues()
        self.check_changes()
        self.check_cross_references()
        self.check_mode_rules()
        return self.problems

    def check_page(self) -> None:
        page = self.p["page"]
        if not self.need(page, "page",
                         ("url", "target", "host", "path", "slug",
                          "conversion_goal", "goal_source")):
            return
        self.enum(page["target"], "page.target", {"website", "shopify_app_store"})
        self.enum(page["goal_source"], "page.goal_source",
                  {"inferred_from_page", "inferred_from_audience_context", "user_specified"})

        for field in ("url", "host", "path", "slug", "conversion_goal"):
            value = page[field]
            if not isinstance(value, str) or not value.strip():
                self.fail(f"page.{field}", "must be a non-empty string")

        # The slug is the filename, and the slug rule is deterministic, so a
        # slug that disagrees with its own host+path is a profile filed under
        # the wrong page — the next audit derives the slug from the URL, finds
        # nothing, and starts a fresh file, orphaning every prior audit.
        host, path, slug = page["host"], page["path"], page["slug"]
        expected_slug = derive_slug(host, path)
        if expected_slug and isinstance(slug, str) and slug != expected_slug:
            self.fail("page.slug",
                      f"{slug!r} != {expected_slug!r} derived from host+path by the "
                      "documented slug rule")

        # page.url must be the page these fields describe, or the profile
        # records one page's findings under another's identity.
        url = page["url"]
        if isinstance(url, str) and url:
            try:
                parts = urlsplit(url)
            except ValueError as exc:
                self.fail("page.url", f"must be a parseable absolute HTTPS URL ({exc})")
                parts = None
            if parts is not None:
                if parts.scheme.lower() != "https" or not parts.netloc or parts.hostname is None:
                    self.fail("page.url", "must be an absolute HTTPS URL")
                if (parts.username is not None or parts.password is not None
                        or ":" in parts.netloc.rsplit("@", 1)[-1]):
                    self.fail("page.url", "must not contain credentials or an explicit port")
                if (parts.hostname and isinstance(host, str)
                        and parts.hostname.lower() != host.lower()):
                    self.fail("page.host",
                              f"{host!r} is not the host of page.url ({parts.hostname!r})")
                if isinstance(path, str):
                    if not path.startswith("/"):
                        self.fail("page.path", "must start with '/'")
                    if "?" in path or "#" in path:
                        self.fail("page.path", "must not contain a query string or fragment")
                    if normalized_page_path(parts.path) != normalized_page_path(path):
                        self.fail("page.path",
                                  f"{path!r} is not the path of page.url ({parts.path!r})")

        # target selects the GA4 scoping regime in SKILL.md Step 2, so a target
        # that disagrees with the host sends the next audit's queries to the
        # wrong property.
        if isinstance(host, str):
            lowered = host.lower()
            if lowered == SHOPIFY_HOST:
                expected_target = "shopify_app_store"
                if (isinstance(path, str)
                        and not SHOPIFY_LISTING_PATH_RE.match(normalized_page_path(path))):
                    self.fail(
                        "page.path",
                        f"{path!r} is not a Shopify App Store app listing "
                        "(expected /<app-handle>)",
                    )
            elif is_public_hostname(lowered):
                expected_target = "website"
            else:
                expected_target = None
            if expected_target is None:
                self.fail("page.host", f"{host!r} is not a public website host")
            elif page["target"] != expected_target:
                self.fail("page.target",
                          f"{page['target']!r} disagrees with host {host!r} "
                          f"(expected {expected_target!r})")

    # -- latest ---------------------------------------------------------------

    def check_latest(self) -> None:
        latest = self.p["latest"]
        if not self.need(latest, "latest",
                         ("audit_id", "audited_at", "scope", "sections_emitted",
                          "date_range", "data_layers",
                          "engineering_checks_run", "engineering_checks_run_observed_in")):
            return

        audit_id = latest["audit_id"]
        if not is_valid_audit_id(audit_id):
            self.fail("latest.audit_id",
                      f"{audit_id!r} must be a real YYYY-MM-DD date, optionally suffixed -N "
                      "starting at -2")
        audited_at = latest["audited_at"]
        if parse_date(audited_at) is None:
            self.fail("latest.audited_at", f"{audited_at!r} must be a real YYYY-MM-DD date")
        elif is_valid_audit_id(audit_id) and audited_at != audit_id[:10]:
            self.fail("latest.audited_at",
                      f"{audited_at!r} must equal the date portion of audit_id {audit_id!r}")
        self.enum(latest["scope"], "latest.scope", {"full", "focused"})

        sections = latest["sections_emitted"]
        if not isinstance(sections, list) or not all(
                is_int(s) and 1 <= s <= 9 for s in sections):
            self.fail("latest.sections_emitted", "must be a list of integers drawn from 1-9")
        elif len(set(sections)) != len(sections):
            self.fail("latest.sections_emitted", "contains duplicates")
        elif latest["scope"] == "full" and set(sections) != set(range(1, 10)):
            self.fail("latest.sections_emitted", "scope 'full' must emit all nine sections")
        elif latest["scope"] == "focused" and set(sections) == set(range(1, 10)):
            self.fail("latest.sections_emitted", "scope 'focused' cannot emit all nine sections")

        window = latest["date_range"]
        if window is not None:
            if self.need(window, "latest.date_range", ("start", "end", "label")):
                start = parse_date(window["start"])
                end = parse_date(window["end"])
                if start is None:
                    self.fail("latest.date_range.start", "must be a real YYYY-MM-DD date")
                if end is None:
                    self.fail("latest.date_range.end", "must be a real YYYY-MM-DD date")
                if start is not None and end is not None and start > end:
                    self.fail("latest.date_range",
                              f"start {window['start']} is after end {window['end']}")

        layers = latest["data_layers"]
        layer_names = {"ga4", "gsc", "session_replay"}
        if self.need(layers, "latest.data_layers", tuple(sorted(layer_names))):
            if set(layers) != layer_names:
                self.fail("latest.data_layers",
                          f"must carry exactly {sorted(layer_names)}")
            for name in layer_names:
                layer = layers.get(name)
                # latest carries the object shape; history collapses to booleans.
                if not self.need(layer, f"latest.data_layers.{name}",
                                 ("available", "source", "note")):
                    self.fail(f"latest.data_layers.{name}",
                              "must be an object with available/source/note")
                    continue
                if not isinstance(layer["available"], bool):
                    self.fail(f"latest.data_layers.{name}.available", "must be a boolean")
                for field in ("source", "note"):
                    value = layer[field]
                    if value is not None and not isinstance(value, str):
                        self.fail(f"latest.data_layers.{name}.{field}",
                                  "must be a string or null")

        page = self.p.get("page")
        if isinstance(page, dict) and page.get("target") == "shopify_app_store":
            gsc = layers.get("gsc") if isinstance(layers, dict) else None
            if isinstance(gsc, dict) and gsc.get("available") is not False:
                self.fail("latest.data_layers.gsc.available",
                          "must be false for the Shopify App Store listing")
            metrics = latest.get("metrics")
            if isinstance(metrics, dict) and metrics.get("gsc") is not None:
                self.fail("latest.metrics.gsc",
                          "must be null for the Shopify App Store listing")

        checks = latest["engineering_checks_run"]
        if not isinstance(checks, list) or not all(
                isinstance(c, str) and CHECK_ID_RE.match(c) for c in checks):
            self.fail("latest.engineering_checks_run",
                      "must be a list of snake_case check ids (empty list when none completed)")
        elif len(set(checks)) != len(checks):
            self.fail("latest.engineering_checks_run", "contains duplicates")

        # The four measured blocks carry observed_in, so a carried-forward block
        # is self-evidently stale. engineering_checks_run has no such marker of
        # its own, which is exactly how a focused slice could inherit a prior
        # run's evidence and resolve an issue nobody re-tested. This stamp makes
        # "rebuilt this run" a checkable fact rather than a prose instruction.
        stamp = latest["engineering_checks_run_observed_in"]
        if stamp != audit_id:
            self.fail("latest.engineering_checks_run_observed_in",
                      f"{stamp!r} != this run's audit_id {audit_id!r} — engineering_checks_run "
                      "is rebuilt from scratch every run (use [] when no check completed), "
                      "never carried forward from the previous latest")

        for block in BLOCKS:
            value = latest.get(block)
            if value is None:
                continue
            if not isinstance(value, dict):
                self.fail(f"latest.{block}", "must be an object or null")
                continue
            observed = value.get("observed_in")
            if not is_valid_audit_id(observed):
                self.fail(f"latest.{block}.observed_in",
                          "every carried block must record the audit that measured it")

        metrics = latest.get("metrics")
        if (isinstance(metrics, dict)
                and metrics.get("observed_in") == audit_id
                and not self.key_metric_names(metrics)):
            self.fail(
                "latest.metrics",
                "a measured metrics block must contain at least one finite, "
                "unambiguous numeric leaf so it can be compacted into history",
            )

        self.check_snapshot(latest.get("page_snapshot"))
        self.check_lift(latest.get("lift"))
        self.check_pxl(latest.get("pxl"))

    def check_snapshot(self, snap: Any) -> None:
        if not isinstance(snap, dict):
            return
        method = snap.get("capture_method")
        self.enum(method, "latest.page_snapshot.capture_method",
                  {"screenshot_desktop_and_mobile", "screenshot_desktop_only",
                   "screenshot_mobile_only", "text_fetch"})
        approx = snap.get("fold_findings_approximate")
        if isinstance(method, str) and isinstance(approx, bool):
            if (method == "text_fetch") != approx:
                self.fail("latest.page_snapshot.fold_findings_approximate",
                          "text_fetch must pair with true; any screenshot method with false")

    def check_lift(self, lift: Any) -> None:
        if not isinstance(lift, dict):
            return
        if not self.need(lift, "latest.lift", ("basis", "total", "max", "factors", "lowest_two")):
            return
        self.enum(lift["basis"], "latest.lift.basis", MODES)
        if lift["max"] != 30:
            self.fail("latest.lift.max", "is always 30")

        factors = lift["factors"]
        if not isinstance(factors, dict) or set(factors) != set(LIFT_FACTORS):
            self.fail("latest.lift.factors", f"must carry exactly {list(LIFT_FACTORS)}")
            return
        scores = {}
        for name, factor in factors.items():
            score = factor.get("score") if isinstance(factor, dict) else None
            if not is_int(score) or not 1 <= score <= 5:
                self.fail(f"latest.lift.factors.{name}.score", "must be an integer 1-5")
                return
            scores[name] = score
            if isinstance(factor, dict) and "search_intent_match" in factor:
                self.enum(factor["search_intent_match"],
                          f"latest.lift.factors.{name}.search_intent_match",
                          {"match", "partial", "mismatch", "unknown"})
        if lift["total"] != sum(scores.values()):
            self.fail("latest.lift.total",
                      f"{lift['total']} != {sum(scores.values())} (sum of the six factors)")
        named = lift["lowest_two"]
        if not isinstance(named, list) or len(named) != 2:
            self.fail("latest.lift.lowest_two", "must be a list of exactly two factor names")
        elif not all(isinstance(k, str) and k in scores for k in named):
            self.fail("latest.lift.lowest_two",
                      f"{named!r} must name two of {list(LIFT_FACTORS)}")
        elif named[0] == named[1]:
            # Comparing sets of scores could not see this: with the bottom two
            # tied, [X, X] produced the same one-element set as the correct
            # answer and passed.
            self.fail("latest.lift.lowest_two", f"names {named[0]!r} twice")
        else:
            # Sorted score pairs, so a tie at the bottom lets either tied
            # factor be named, but a factor scoring above the cut cannot be.
            cutoff = sorted(scores.values())[:2]
            if sorted(scores[k] for k in named) != cutoff:
                self.fail("latest.lift.lowest_two",
                          f"{named!r} are not the two lowest-scoring factors")

    def check_pxl(self, pxl: Any) -> None:
        if not isinstance(pxl, dict):
            return
        if not self.need(pxl, "latest.pxl", ("scoring_mode", "ideas")):
            return
        mode = pxl["scoring_mode"]
        self.enum(mode, "latest.pxl.scoring_mode", MODES)
        ideas = pxl["ideas"]
        if not isinstance(ideas, list):
            self.fail("latest.pxl.ideas", "must be an array")
            return

        ranks: list[int] = []
        ranked_ids: set[str] = set()
        for index, idea in enumerate(ideas):
            where = f"latest.pxl.ideas[{index}]"
            if not self.need(idea, where,
                             ("experiment_id", "rank", "name", "element_type", "score",
                              "unknown_points", "max_achievable", "priority", "criteria")):
                continue
            self.enum(idea["element_type"], f"{where}.element_type", ELEMENT_TYPES)
            experiment_id = idea["experiment_id"]
            if not isinstance(experiment_id, str) or not experiment_id:
                self.fail(f"{where}.experiment_id", "must be a non-empty string")
            elif experiment_id in ranked_ids:
                self.fail(f"{where}.experiment_id",
                          f"duplicate ranked experiment id {experiment_id!r}")
            else:
                ranked_ids.add(experiment_id)

            total = unknown = 0
            criteria = idea["criteria"]
            if not isinstance(criteria, dict) or set(criteria) != set(PXL_POINTS):
                self.fail(f"{where}.criteria", f"must carry exactly {sorted(PXL_POINTS)}")
                continue
            broken = False
            for group, points in PXL_POINTS.items():
                block = criteria[group]
                expected_keys = set(points) | {"subtotal", "max"}
                if not isinstance(block, dict) or set(block) != expected_keys:
                    self.fail(f"{where}.criteria.{group}",
                              f"must carry exactly {sorted(expected_keys)}")
                    broken = True
                    continue
                for key in points:
                    # Identity, not equality: `0 == False` in Python, so an `in`
                    # test would quietly accept a criterion stored as 0 — the
                    # exact unknown-vs-zero collapse this schema exists to stop.
                    if not any(block[key] is allowed for allowed in (True, False, None)):
                        self.fail(f"{where}.criteria.{group}.{key}",
                                  f"{block[key]!r} must be true, false, or null (unknown) — never 0/1")
                        broken = True
                subtotal = sum(p for k, p in points.items() if block.get(k) is True)
                if not is_int(block.get("subtotal")) or block["subtotal"] != subtotal:
                    self.fail(f"{where}.criteria.{group}.subtotal",
                              f"{block.get('subtotal')!r} != {subtotal} (points from true answers)")
                    broken = True
                if block.get("max") != sum(points.values()):
                    self.fail(f"{where}.criteria.{group}.max",
                              f"must be {sum(points.values())}")
                total += subtotal
                unknown += sum(p for k, p in points.items() if block.get(k) is None)
            if broken:
                continue

            if not is_int(idea["rank"]) or idea["rank"] < 1:
                self.fail(f"{where}.rank", f"{idea['rank']!r} must be a positive integer")
            else:
                ranks.append(idea["rank"])
            if not is_int(idea["score"]) or idea["score"] != total:
                self.fail(f"{where}.score", f"{idea['score']!r} != {total} (sum of subtotals)")
            if not is_int(idea["unknown_points"]) or idea["unknown_points"] != unknown:
                self.fail(f"{where}.unknown_points",
                          f"{idea['unknown_points']!r} != {unknown} (points answered null)")
            if not is_int(idea["max_achievable"]) or idea["max_achievable"] != PXL_MAX - unknown:
                self.fail(f"{where}.max_achievable", f"must be {PXL_MAX} - unknown_points")
            expected = None if mode == "heuristic_only" else tier(total)
            if idea["priority"] != expected:
                self.fail(f"{where}.priority",
                          f"{idea['priority']!r} — expected {expected!r}"
                          + (" (tiers are not assigned in heuristic-only mode)"
                             if expected is None else ""))
        if len(ranks) != len(set(ranks)):
            self.fail("latest.pxl.ideas[].rank",
                      f"ranks must be unique within the current ranking, found {ranks!r}")
        elif len(ranks) == len(ideas) and ranks != list(range(1, len(ideas) + 1)):
            self.fail(
                "latest.pxl.ideas[].rank",
                f"ideas must be ordered with contiguous ranks 1..{len(ideas)}, "
                f"found {ranks!r}",
            )

    # -- history --------------------------------------------------------------

    def check_history(self) -> None:
        history = self.p["history"]
        if not isinstance(history, list):
            return
        if len(history) > 12:
            self.fail("history", f"keeps the 12 most recent snapshots, found {len(history)}")
        latest = self.p["latest"] if isinstance(self.p.get("latest"), dict) else {}
        latest_id = latest.get("audit_id")
        seen_ids: set[str] = set()
        order: list[tuple[str, int]] = []
        for index, snap in enumerate(history):
            where = f"history[{index}]"
            if not self.need(
                    snap, where,
                    ("audit_id", "audited_at", "scope", "measured", "date_range",
                     "data_layers", "page_snapshot", "lift", "pxl", "key_metrics",
                     "open_sev0_count")):
                continue
            audit_id = snap["audit_id"]
            if not is_valid_audit_id(audit_id):
                self.fail(f"{where}.audit_id",
                          f"{audit_id!r} must be a real YYYY-MM-DD date, optionally "
                          "suffixed -N starting at -2")
            else:
                if audit_id in seen_ids:
                    self.fail(f"{where}.audit_id", f"duplicate history audit id {audit_id!r}")
                seen_ids.add(audit_id)
                if audit_id == latest_id:
                    self.fail(f"{where}.audit_id",
                              "must not duplicate latest.audit_id")
                order.append(audit_sort_key(audit_id))
                if snap["audited_at"] != audit_id[:10]:
                    self.fail(f"{where}.audited_at",
                              f"{snap['audited_at']!r} must equal the date portion of audit_id")
            if parse_date(snap["audited_at"]) is None:
                self.fail(f"{where}.audited_at", "must be a real YYYY-MM-DD date")
            self.enum(snap["scope"], f"{where}.scope", {"full", "focused"})

            measured = snap["measured"]
            if not isinstance(measured, dict) or set(measured) != set(BLOCKS):
                self.fail(f"{where}.measured", f"must carry exactly {list(BLOCKS)}")
                continue
            for block, value in measured.items():
                if not isinstance(value, bool):
                    self.fail(f"{where}.measured.{block}",
                              f"{value!r} must be a JSON boolean, never 0/1")

            window = snap["date_range"]
            if window is not None:
                if self.need(window, f"{where}.date_range", ("start", "end", "label")):
                    start, end = window["start"], window["end"]
                    start_date = parse_date(start)
                    end_date = parse_date(end)
                    if start_date is None:
                        self.fail(f"{where}.date_range.start",
                                  "must be a real YYYY-MM-DD date")
                    if end_date is None:
                        self.fail(f"{where}.date_range.end",
                                  "must be a real YYYY-MM-DD date")
                    if (start_date is not None and end_date is not None
                            and start_date > end_date):
                        self.fail(f"{where}.date_range", f"start {start} is after end {end}")

            layers = snap["data_layers"]
            if (not isinstance(layers, dict)
                    or set(layers) != {"ga4", "gsc", "session_replay"}
                    or not all(isinstance(v, bool) for v in layers.values())):
                self.fail(f"{where}.data_layers",
                          "must carry exactly ga4/gsc/session_replay as booleans")
            if not is_int(snap["open_sev0_count"]) or snap["open_sev0_count"] < 0:
                self.fail(f"{where}.open_sev0_count", "must be a non-negative integer")
            if "engineering_checks_run" in snap:
                self.fail(f"{where}.engineering_checks_run",
                          "is current-run evidence only and is never copied into history")
            for block, key in (("metrics", "key_metrics"), ("lift", "lift"),
                               ("pxl", "pxl"), ("page_snapshot", "page_snapshot")):
                if measured.get(block) is False and snap.get(key) is not None:
                    self.fail(f"{where}.{key}",
                              "unmeasured blocks are stored as null, never carried forward")
                if measured.get(block) is True and snap.get(key) is None:
                    self.fail(f"{where}.{key}", "measured block is missing")
            if measured.get("metrics") and isinstance(snap.get("key_metrics"), dict):
                key_metrics = snap["key_metrics"]
                if not key_metrics:
                    self.fail(f"{where}.key_metrics",
                              "a measured metrics block must retain at least one numeric metric")
                for name, value in key_metrics.items():
                    if not isinstance(name, str) or not name:
                        self.fail(f"{where}.key_metrics",
                                  "metric names must be non-empty strings")
                    if not is_number(value):
                        self.fail(f"{where}.key_metrics.{name}",
                                  "must be a finite JSON number")
            if measured.get("page_snapshot") and isinstance(snap.get("page_snapshot"), dict):
                if set(snap["page_snapshot"]) != {"headline", "primary_cta_text"}:
                    self.fail(f"{where}.page_snapshot",
                              "history stores exactly headline and primary_cta_text")
            if measured.get("lift") and isinstance(snap.get("lift"), dict):
                factors = snap["lift"].get("factors")
                if isinstance(factors, dict) and set(factors) == set(LIFT_FACTORS):
                    invalid_factors = {
                        name: value for name, value in factors.items()
                        if not is_int(value) or not 1 <= value <= 5
                    }
                    if invalid_factors:
                        self.fail(
                            f"{where}.lift.factors",
                            "must contain integer scores from 1-5; "
                            f"invalid values {invalid_factors!r}",
                        )
                    elif (not is_int(snap["lift"].get("total"))
                          or snap["lift"].get("total") != sum(factors.values())):
                        self.fail(f"{where}.lift.total", "does not equal the sum of its factors")
                else:
                    self.fail(f"{where}.lift.factors", f"must carry exactly {list(LIFT_FACTORS)}")
            if measured.get("pxl") and isinstance(snap.get("pxl"), dict):
                compact_pxl = snap["pxl"]
                self.enum(compact_pxl.get("scoring_mode"),
                          f"{where}.pxl.scoring_mode", MODES)
                top_3 = compact_pxl.get("top_3")
                if (not isinstance(top_3, list)
                        or len(top_3) > 3
                        or not all(isinstance(item, str) and item for item in top_3)
                        or len(top_3) != len(set(top_3))):
                    self.fail(f"{where}.pxl.top_3",
                              "must be an ordered list of at most three unique string ids")

        if order != sorted(order, reverse=True):
            self.fail("history",
                      "must be newest first by audit_id, including same-day numeric suffixes")
        if (is_valid_audit_id(latest_id)
                and order and audit_sort_key(latest_id) <= order[0]):
            self.fail("latest.audit_id",
                      "must be newer than the newest retained history snapshot")

    # -- longitudinal ---------------------------------------------------------

    def check_experiments(self) -> None:
        experiments = self.p["experiments"]
        if not isinstance(experiments, list):
            return
        seen: set[str] = set()
        for index, exp in enumerate(experiments):
            where = f"experiments[{index}]"
            if not self.need(exp, where,
                             ("id", "name", "hypothesis", "element_type", "primary_metric",
                              "created_in_audit", "last_seen_in_audit",
                              "status", "status_source", "outcome")):
                continue
            experiment_id = exp["id"]
            if not isinstance(experiment_id, str) or not experiment_id:
                self.fail(f"{where}.id", "must be a non-empty string")
            elif experiment_id in seen:
                self.fail(where, f"duplicate experiment id {experiment_id!r}")
            else:
                seen.add(experiment_id)
            for field in ("name", "hypothesis", "primary_metric"):
                if not isinstance(exp[field], str) or not exp[field].strip():
                    self.fail(f"{where}.{field}", "must be a non-empty string")
            self.enum(exp["element_type"], f"{where}.element_type", ELEMENT_TYPES)
            status = exp["status"]
            status_source = exp["status_source"]
            self.enum(status, f"{where}.status", STATUSES)
            self.enum(status_source, f"{where}.status_source", {"audit", "user_reported"})
            if (status_source == "audit"
                    and (not isinstance(status, str) or status not in SKILL_SETTABLE)):
                self.fail(f"{where}.status",
                          f"{status!r} is user-reported only — the skill never sets it")
            if (status_source == "user_reported" and isinstance(status, str)
                    and status in SKILL_SETTABLE):
                self.fail(f"{where}.status",
                          f"{status!r} is audit-owned; user_reported is reserved for "
                          "running/outcome/rollout decisions")
            created = exp["created_in_audit"]
            last_seen = exp["last_seen_in_audit"]
            for field, value in (
                    ("created_in_audit", created), ("last_seen_in_audit", last_seen)):
                if not is_valid_audit_id(value):
                    self.fail(f"{where}.{field}",
                              f"{value!r} must be a real YYYY-MM-DD[-N] audit id")
            if (is_valid_audit_id(created) and is_valid_audit_id(last_seen)
                    and audit_sort_key(created) > audit_sort_key(last_seen)):
                self.fail(where, "created_in_audit cannot be newer than last_seen_in_audit")
            latest_id = (
                self.p.get("latest", {}).get("audit_id")
                if isinstance(self.p.get("latest"), dict)
                else None
            )
            if (is_valid_audit_id(last_seen) and is_valid_audit_id(latest_id)
                    and audit_sort_key(last_seen) > audit_sort_key(latest_id)):
                self.fail(f"{where}.last_seen_in_audit",
                          "cannot be newer than latest.audit_id")
            outcome = exp["outcome"]
            if outcome is not None:
                if self.need(outcome, f"{where}.outcome", ("result",)):
                    self.enum(outcome["result"], f"{where}.outcome.result",
                              {"win", "loss", "inconclusive"})
                if status_source != "user_reported":
                    self.fail(f"{where}.outcome",
                              "an outcome is user-reported; status_source must say so")
            expected_result = {
                "won": "win",
                "lost": "loss",
                "inconclusive": "inconclusive",
            }.get(status) if isinstance(status, str) else None
            if expected_result is not None:
                if not isinstance(outcome, dict):
                    self.fail(f"{where}.outcome",
                              f"status {status!r} requires a matching outcome")
                elif outcome.get("result") != expected_result:
                    self.fail(
                        f"{where}.outcome.result",
                        f"status {status!r} requires result {expected_result!r}",
                    )
            elif status == "shipped":
                if not isinstance(outcome, dict):
                    self.fail(f"{where}.outcome",
                              "a shipped experiment must carry its prior result")
                elif (not isinstance(outcome.get("result"), str)
                      or outcome.get("result") not in {"win", "inconclusive"}):
                    self.fail(
                        f"{where}.outcome.result",
                        "a shipped rollout must come from a win or an inconclusive result",
                    )
            elif outcome is not None:
                self.fail(
                    f"{where}.outcome",
                    f"status {status!r} cannot carry a terminal test outcome",
                )

    def check_issues(self) -> None:
        issues = self.p["engineering_issues"]
        if not isinstance(issues, list):
            return
        latest = self.p["latest"] if isinstance(self.p.get("latest"), dict) else {}
        checks_run = latest.get("engineering_checks_run")
        checks_run = (
            {check for check in checks_run if isinstance(check, str)}
            if isinstance(checks_run, list)
            else set()
        )
        audit_id = latest.get("audit_id")
        seen: set[str] = set()
        for index, issue in enumerate(issues):
            where = f"engineering_issues[{index}]"
            if not self.need(issue, where,
                             ("id", "issue", "source", "check_id", "severity",
                              "recommended_fix", "first_seen", "last_seen",
                              "status", "resolved_in_audit", "blocks_experiments")):
                continue
            issue_id = issue["id"]
            if not isinstance(issue_id, str) or not issue_id:
                self.fail(f"{where}.id", "must be a non-empty string")
            elif issue_id in seen:
                self.fail(where, f"duplicate issue id {issue_id!r}")
            else:
                seen.add(issue_id)
            self.enum(issue["severity"], f"{where}.severity", SEVERITIES)
            self.enum(issue["status"], f"{where}.status", {"open", "fixed"})
            if not (isinstance(issue["source"], str) and issue["source"]):
                self.fail(f"{where}.source", "must be a non-empty token (open set)")
            if not (isinstance(issue["check_id"], str) and CHECK_ID_RE.match(issue["check_id"])):
                self.fail(f"{where}.check_id",
                          "every issue names the exact snake_case check that detects it")
            if not isinstance(issue["blocks_experiments"], list):
                self.fail(f"{where}.blocks_experiments", "must be an array")
            elif not all(isinstance(item, str) for item in issue["blocks_experiments"]):
                self.fail(f"{where}.blocks_experiments",
                          "must contain only string experiment ids")
            for field in ("first_seen", "last_seen"):
                value = issue[field]
                if not is_valid_audit_id(value):
                    self.fail(f"{where}.{field}",
                              f"{value!r} must be a real YYYY-MM-DD[-N] audit id")
            if (is_valid_audit_id(issue["first_seen"])
                    and is_valid_audit_id(issue["last_seen"])
                    and audit_sort_key(issue["first_seen"]) > audit_sort_key(issue["last_seen"])):
                self.fail(where, "first_seen cannot be newer than last_seen")
            if (is_valid_audit_id(issue["last_seen"]) and is_valid_audit_id(audit_id)
                    and audit_sort_key(issue["last_seen"]) > audit_sort_key(audit_id)):
                self.fail(f"{where}.last_seen", "cannot be newer than latest.audit_id")

            # Payload-only checks establish shape and chronology. The transition
            # from open -> fixed is checked against the locked canonical profile
            # in validate_transition(), because an old legitimate resolution does
            # not need to appear in this run's engineering_checks_run.
            if issue["status"] == "fixed":
                resolved = issue["resolved_in_audit"]
                if not is_valid_audit_id(resolved):
                    self.fail(f"{where}.resolved_in_audit",
                              "a fixed issue records a real YYYY-MM-DD[-N] audit id")
                elif (is_valid_audit_id(audit_id)
                      and audit_sort_key(resolved) > audit_sort_key(audit_id)):
                    self.fail(f"{where}.resolved_in_audit",
                              "cannot name an audit newer than latest.audit_id")
                elif (resolved == audit_id
                      and (not isinstance(issue.get("check_id"), str)
                           or issue.get("check_id") not in checks_run)):
                    self.fail(f"{where}.status",
                              f"resolved this run but its check {issue.get('check_id')!r} is not in "
                              "latest.engineering_checks_run — a missing signal is never a fix")
            elif issue["resolved_in_audit"] is not None:
                self.fail(f"{where}.resolved_in_audit", "must be null while the issue is open")

    def check_changes(self) -> None:
        """Enforce the per-block comparison contract from Write algorithm step 7."""
        latest = self.p["latest"] if isinstance(self.p.get("latest"), dict) else {}
        history = self.p["history"] if isinstance(self.p.get("history"), list) else []
        changes = latest.get("changes_since_previous")
        if not history or changes is None:
            return  # check_mode_rules owns first-audit/re-audit presence
        if not isinstance(changes, dict):
            self.fail("latest.changes_since_previous", "must be an object")
            return
        missing = sorted(ROLLUP_FIELDS - set(changes))
        if missing:
            self.fail("latest.changes_since_previous",
                      f"missing required field(s) {missing}")
            return

        latest_id = latest.get("audit_id")
        head_id = history[0].get("audit_id") if isinstance(history[0], dict) else None
        if changes["compared_to"] != head_id:
            self.fail("latest.changes_since_previous.compared_to",
                      f"{changes['compared_to']!r} must equal the head of history {head_id!r}")

        compared = changes["compared_against"]
        if not isinstance(compared, dict) or set(compared) != set(DELTA_BLOCKS):
            self.fail("latest.changes_since_previous.compared_against",
                      f"must carry exactly {list(DELTA_BLOCKS)}")
            compared = {}

        not_compared = changes["not_compared"]
        reasons: dict[str, str] = {}
        if not isinstance(not_compared, list):
            self.fail("latest.changes_since_previous.not_compared",
                      "must be an array of '<block> <reason>' strings")
        else:
            for item in not_compared:
                if not isinstance(item, str) or not item.strip():
                    self.fail("latest.changes_since_previous.not_compared",
                              f"{item!r} must be a non-empty reason string")
                    continue
                matched = next(
                    (block for block in DELTA_BLOCKS
                     if re.match(rf"^{re.escape(block)}\b", item.strip(), re.I)),
                    None,
                )
                if matched is None:
                    self.fail("latest.changes_since_previous.not_compared",
                              f"{item!r} must start with metrics, lift, or pxl")
                elif matched in reasons:
                    self.fail("latest.changes_since_previous.not_compared",
                              f"contains more than one reason for {matched}")
                else:
                    reasons[matched] = item

        if not isinstance(changes["comparable"], bool):
            self.fail("latest.changes_since_previous.comparable", "must be a boolean")
        if not isinstance(changes["comparability_note"], str):
            self.fail("latest.changes_since_previous.comparability_note", "must be a string")

        source_by_block: dict[str, dict[str, Any] | None] = {}
        measured_now: dict[str, bool] = {}
        history_keys = {
            "metrics": "key_metrics",
            "lift": "lift",
            "pxl": "pxl",
        }
        for block in DELTA_BLOCKS:
            current = latest.get(block)
            measured = (isinstance(current, dict)
                        and current.get("observed_in") == latest_id)
            measured_now[block] = measured
            source = next(
                (
                    snap for snap in history
                    if isinstance(snap, dict)
                    and isinstance(snap.get("measured"), dict)
                    and snap["measured"].get(block) is True
                    and snap.get(history_keys[block]) is not None
                ),
                None,
            )
            source_by_block[block] = source
            expected = source.get("audit_id") if measured and source else None
            if compared.get(block) != expected:
                self.fail(f"latest.changes_since_previous.compared_against.{block}",
                          f"{compared.get(block)!r} must be {expected!r} — the most recent "
                          "history snapshot that genuinely measured this block, or null "
                          "when this run did not measure it / no source exists")
            should_explain = not measured or source is None
            if should_explain and block not in reasons:
                self.fail("latest.changes_since_previous.not_compared",
                          f"must explain why {block} was not compared")
            if not should_explain and block in reasons:
                self.fail("latest.changes_since_previous.not_compared",
                          f"must not list {block}; this run and {expected!r} both measured it")

        self.check_lift_deltas(changes, latest, source_by_block["lift"], measured_now["lift"])
        self.check_metric_deltas(
            changes, latest, source_by_block["metrics"], measured_now["metrics"])
        self.check_pxl_rollup(
            changes, latest, source_by_block["pxl"], measured_now["pxl"])
        self.check_comparability(
            changes,
            latest,
            source_by_block,
            measured_now,
        )

        audit_id = latest.get("audit_id")
        issues = self.p.get("engineering_issues")
        issue_records = issues if isinstance(issues, list) else []
        expected_new_issues = {
            issue.get("id") for issue in issue_records
            if (isinstance(issue, dict)
                and isinstance(issue.get("id"), str)
                and issue.get("first_seen") == audit_id)
        }
        expected_resolved_issues = {
            issue.get("id") for issue in issue_records
            if (isinstance(issue, dict)
                and isinstance(issue.get("id"), str)
                and issue.get("resolved_in_audit") == audit_id)
        }
        self.check_id_list(changes, "new_issues", expected_new_issues)
        self.check_id_list(changes, "resolved_issues", expected_resolved_issues)

    def check_lift_deltas(
            self, changes: dict[str, Any], latest: dict[str, Any],
            source: dict[str, Any] | None, measured: bool) -> None:
        delta_total = changes["lift_total_delta"]
        deltas = changes["lift_deltas"]
        current = latest.get("lift")
        prior = source.get("lift") if source else None
        comparable = measured and isinstance(current, dict) and isinstance(prior, dict)
        if not comparable:
            if delta_total is not None:
                self.fail("latest.changes_since_previous.lift_total_delta",
                          "must be null when lift was not compared")
            if deltas != {}:
                self.fail("latest.changes_since_previous.lift_deltas",
                          "must be {} when lift was not compared")
            return

        current_factors = current.get("factors")
        prior_factors = prior.get("factors")
        if not (isinstance(current_factors, dict)
                and isinstance(prior_factors, dict)
                and set(current_factors) == set(LIFT_FACTORS)
                and set(prior_factors) == set(LIFT_FACTORS)):
            self.fail("latest.changes_since_previous.lift_deltas",
                      "cannot validate without all six current and source factors")
            return
        current_total, prior_total = current.get("total"), prior.get("total")
        if not is_number(current_total) or not is_number(prior_total):
            self.fail("latest.changes_since_previous.lift_total_delta",
                      "cannot validate without numeric current and source totals")
            return
        expected_total = current_total - prior_total
        if not (is_number(delta_total) and self.numbers_equal(delta_total, expected_total)):
            self.fail("latest.changes_since_previous.lift_total_delta",
                      f"{delta_total!r} != {expected_total!r}")
        if not isinstance(deltas, dict) or set(deltas) != set(LIFT_FACTORS):
            self.fail("latest.changes_since_previous.lift_deltas",
                      f"must carry exactly {list(LIFT_FACTORS)}")
            return
        for factor in LIFT_FACTORS:
            current_factor = current_factors[factor]
            current_score = (current_factor.get("score")
                             if isinstance(current_factor, dict) else None)
            prior_score = prior_factors[factor]
            if not is_number(current_score) or not is_number(prior_score):
                self.fail(f"latest.changes_since_previous.lift_deltas.{factor}",
                          "cannot validate without numeric current and source scores")
                continue
            expected = current_score - prior_score
            if not (is_number(deltas[factor])
                    and self.numbers_equal(deltas[factor], expected)):
                self.fail(f"latest.changes_since_previous.lift_deltas.{factor}",
                          f"{deltas[factor]!r} != {expected!r}")
        if (all(is_number(value) for value in deltas.values())
                and is_number(delta_total)
                and not self.numbers_equal(sum(deltas.values()), delta_total)):
            self.fail("latest.changes_since_previous.lift_deltas",
                      "factor deltas must sum to lift_total_delta")

    def check_metric_deltas(
            self, changes: dict[str, Any], latest: dict[str, Any],
            source: dict[str, Any] | None, measured: bool) -> None:
        deltas = changes["metric_deltas"]
        current = latest.get("metrics")
        prior = source.get("key_metrics") if source else None
        comparable = measured and isinstance(current, dict) and isinstance(prior, dict)
        if not comparable:
            if deltas != {}:
                self.fail("latest.changes_since_previous.metric_deltas",
                          "must be {} when metrics were not compared")
            return
        if not isinstance(deltas, dict):
            self.fail("latest.changes_since_previous.metric_deltas", "must be an object")
            return
        for metric, claimed in deltas.items():
            previous = prior.get(metric)
            current_value = self.find_metric(current, metric)
            if not is_number(previous) or current_value is None:
                self.fail(f"latest.changes_since_previous.metric_deltas.{metric}",
                          "must name a numeric metric measured in both current metrics "
                          "and the source snapshot's key_metrics")
                continue
            expected = current_value - previous
            if not (is_number(claimed) and self.numbers_equal(claimed, expected)):
                self.fail(f"latest.changes_since_previous.metric_deltas.{metric}",
                          f"{claimed!r} != {expected!r}")

    def check_pxl_rollup(
            self, changes: dict[str, Any], latest: dict[str, Any],
            source: dict[str, Any] | None, measured: bool) -> None:
        current_pxl = latest.get("pxl")
        prior_pxl = source.get("pxl") if source else None
        if not (measured and isinstance(current_pxl, dict) and isinstance(prior_pxl, dict)):
            for field in ("new_experiments", "recurring_experiments",
                          "dropped_experiments"):
                self.check_id_list(changes, field, set())
            if changes["rank_changes"] != {}:
                self.fail("latest.changes_since_previous.rank_changes",
                          "must be {} when PXL was not compared")
            return

        ideas = current_pxl.get("ideas")
        prior_ids = prior_pxl.get("top_3")
        if not isinstance(ideas, list) or not isinstance(prior_ids, list):
            self.fail("latest.changes_since_previous",
                      "cannot validate PXL roll-up without current ideas and source top_3")
            return
        current_ranks = {
            idea.get("experiment_id"): idea.get("rank")
            for idea in ideas
            if (isinstance(idea, dict)
                and isinstance(idea.get("experiment_id"), str)
                and is_int(idea.get("rank")))
        }
        current_ids = set(current_ranks)
        prior_ranks = {
            experiment_id: index
            for index, experiment_id in enumerate(prior_ids, 1)
            if isinstance(experiment_id, str)
        }
        prior_set = set(prior_ranks)
        experiments = self.p.get("experiments")
        experiment_by_id = {
            exp.get("id"): exp
            for exp in (experiments if isinstance(experiments, list) else [])
            if isinstance(exp, dict) and isinstance(exp.get("id"), str)
        }
        latest_id = latest.get("audit_id")
        expected_new = {
            experiment_id for experiment_id in current_ids
            if experiment_by_id.get(experiment_id, {}).get("created_in_audit") == latest_id
        }
        expected_recurring = current_ids & prior_set
        suppressed = {"won", "lost", "shipped", "running", "abandoned"}
        expected_dropped = {
            experiment_id for experiment_id in prior_set - current_ids
            if (
                not isinstance(
                    experiment_by_id.get(experiment_id, {}).get("status"), str
                )
                or experiment_by_id.get(experiment_id, {}).get("status") not in suppressed
            )
        }
        self.check_id_list(changes, "new_experiments", expected_new)
        self.check_id_list(changes, "recurring_experiments", expected_recurring)
        self.check_id_list(changes, "dropped_experiments", expected_dropped)

        expected_rank_changes = {
            experiment_id: {
                "from": prior_ranks[experiment_id],
                "to": current_ranks[experiment_id],
            }
            for experiment_id in expected_recurring
            if prior_ranks[experiment_id] != current_ranks[experiment_id]
        }
        if changes["rank_changes"] != expected_rank_changes:
            self.fail("latest.changes_since_previous.rank_changes",
                      f"{changes['rank_changes']!r} != {expected_rank_changes!r}")

    def check_comparability(
            self, changes: dict[str, Any], latest: dict[str, Any],
            source_by_block: dict[str, dict[str, Any] | None],
            measured_now: dict[str, bool]) -> None:
        """Reject a true comparison when a deterministic incompatibility exists.

        Material redesign remains a human judgment. Scoring-mode, analytics
        window, and contributing-layer availability changes are mechanical and
        must never depend on prose compliance.
        """
        reasons: list[str] = []

        pxl_source = source_by_block.get("pxl")
        current_pxl = latest.get("pxl")
        prior_pxl = pxl_source.get("pxl") if isinstance(pxl_source, dict) else None
        if (measured_now.get("pxl")
                and isinstance(current_pxl, dict)
                and isinstance(prior_pxl, dict)
                and current_pxl.get("scoring_mode") != prior_pxl.get("scoring_mode")):
            reasons.append(
                "PXL scoring_mode differs "
                f"({prior_pxl.get('scoring_mode')!r} -> "
                f"{current_pxl.get('scoring_mode')!r})"
            )

        metric_source = source_by_block.get("metrics")
        metric_deltas = changes.get("metric_deltas")
        current_metrics = latest.get("metrics")
        if (measured_now.get("metrics")
                and isinstance(metric_source, dict)
                and isinstance(metric_deltas, dict)
                and metric_deltas):
            current_days = self.window_days(latest.get("date_range"))
            prior_days = self.window_days(metric_source.get("date_range"))
            if current_days is None or prior_days is None:
                reasons.append("a metrics comparison window is missing or invalid")
            elif current_days != prior_days:
                reasons.append(
                    f"metrics window lengths differ ({prior_days} vs {current_days} days)")

            current_layers = latest.get("data_layers")
            prior_layers = metric_source.get("data_layers")
            if isinstance(current_layers, dict) and isinstance(prior_layers, dict):
                for metric in metric_deltas:
                    for layer_name in self.metric_layers(current_metrics, metric):
                        current_layer = current_layers.get(layer_name)
                        current_available = (
                            current_layer.get("available")
                            if isinstance(current_layer, dict)
                            else None
                        )
                        if (isinstance(current_available, bool)
                                and isinstance(prior_layers.get(layer_name), bool)
                                and current_available != prior_layers[layer_name]):
                            reasons.append(
                                f"{layer_name} availability changed for metric {metric!r}")

        if reasons and changes.get("comparable") is True:
            self.fail(
                "latest.changes_since_previous.comparable",
                "must be false because " + "; ".join(dict.fromkeys(reasons)),
            )
        note = changes.get("comparability_note")
        if changes.get("comparable") is False and (
                not isinstance(note, str) or not note.strip()):
            self.fail(
                "latest.changes_since_previous.comparability_note",
                "must explain why comparable is false",
            )

    @staticmethod
    def window_days(window: Any) -> int | None:
        if not isinstance(window, dict):
            return None
        start, end = window.get("start"), window.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            return None
        try:
            return (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1
        except ValueError:
            return None

    @staticmethod
    def metric_layers(metrics: Any, name: str) -> set[str]:
        """Return recognized data layers containing numeric leaves named *name*."""
        if not isinstance(metrics, dict):
            return set()

        def contains(value: Any) -> bool:
            if isinstance(value, dict):
                return any(
                    (key == name and is_number(child)) or contains(child)
                    for key, child in value.items()
                )
            if isinstance(value, list):
                return any(contains(child) for child in value)
            return False

        return {
            layer for layer in ("ga4", "gsc", "session_replay")
            if contains(metrics.get(layer))
        }

    def check_id_list(
            self, changes: dict[str, Any], field: str, expected: set[Any]) -> None:
        value = changes[field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            self.fail(f"latest.changes_since_previous.{field}",
                      "must be an array of string ids")
            return
        if len(value) != len(set(value)):
            self.fail(f"latest.changes_since_previous.{field}",
                      "must be an array with no duplicate ids")
            return
        if set(value) != expected:
            self.fail(f"latest.changes_since_previous.{field}",
                      f"{value!r} != {sorted(expected, key=str)!r}")

    @staticmethod
    def numbers_equal(left: int | float, right: int | float) -> bool:
        return abs(left - right) <= 1e-9

    @staticmethod
    def find_metric(metrics: dict[str, Any], name: str) -> int | float | None:
        """Find one unambiguous numeric metric by key in the current metrics tree."""
        found: list[int | float] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == name and is_number(child):
                        found.append(child)
                    else:
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(metrics)
        return found[0] if len(found) == 1 else None

    @staticmethod
    def key_metric_names(metrics: Any) -> tuple[str, ...]:
        """Return every numeric leaf name that occurs exactly once.

        History uses unqualified metric names, so a repeated leaf name is
        ambiguous even when the values happen to be equal. Excluding it is safer
        than silently binding a future delta to whichever layer was visited
        first.
        """
        occurrences: dict[str, int] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key != "observed_in" and is_number(child):
                        occurrences[key] = occurrences.get(key, 0) + 1
                    else:
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(metrics)
        return tuple(sorted(name for name, count in occurrences.items() if count == 1))

    def check_cross_references(self) -> None:
        experiments = self.p.get("experiments")
        issues = self.p.get("engineering_issues")
        experiment_records = experiments if isinstance(experiments, list) else []
        issue_records = issues if isinstance(issues, list) else []
        exp_ids = {e["id"] for e in experiment_records
                   if isinstance(e, dict) and isinstance(e.get("id"), str)}
        issue_ids = {e["id"] for e in issue_records
                     if isinstance(e, dict) and isinstance(e.get("id"), str)}
        for issue in issue_records:
            if isinstance(issue, dict) and isinstance(issue.get("blocks_experiments"), list):
                for ref in issue["blocks_experiments"]:
                    if isinstance(ref, str) and ref not in exp_ids:
                        self.fail(f"engineering_issues[{issue.get('id')}].blocks_experiments",
                                  f"{ref!r} has no experiments[] entry")
        latest = self.p["latest"] if isinstance(self.p.get("latest"), dict) else {}
        pxl = latest.get("pxl")
        if isinstance(pxl, dict) and isinstance(pxl.get("ideas"), list):
            for idea in pxl["ideas"]:
                if (isinstance(idea, dict)
                        and isinstance(idea.get("experiment_id"), str)
                        and idea.get("experiment_id") not in exp_ids):
                    self.fail("latest.pxl.ideas",
                              f"ranked idea {idea.get('experiment_id')!r} has no experiments[] entry")
        chg = latest.get("changes_since_previous")
        if isinstance(chg, dict):
            for field in ("new_experiments", "recurring_experiments", "dropped_experiments"):
                refs = chg.get(field)
                for ref in (refs if isinstance(refs, list) else []):
                    if isinstance(ref, str) and ref not in exp_ids:
                        self.fail(f"changes_since_previous.{field}",
                                  f"{ref!r} has no experiments[] entry")
            for field in ("new_issues", "resolved_issues"):
                refs = chg.get(field)
                for ref in (refs if isinstance(refs, list) else []):
                    if isinstance(ref, str) and ref not in issue_ids:
                        self.fail(f"changes_since_previous.{field}",
                                  f"{ref!r} has no engineering_issues[] entry")

    def check_mode_rules(self) -> None:
        latest = self.p["latest"] if isinstance(self.p.get("latest"), dict) else {}
        history = self.p["history"] if isinstance(self.p.get("history"), list) else []
        has_changes = "changes_since_previous" in latest
        if self.mode == "recovery":
            # A recovery snapshot must never imply it inherited the canonical
            # file's history, and has no safe base to diff against.
            if history:
                self.fail("history",
                          "a recovery write is a standalone current-run profile; history must be []")
            if has_changes:
                self.fail("latest.changes_since_previous",
                          "a recovery write has no safe comparison base; omit it")
        else:
            if not history and has_changes:
                self.fail("latest.changes_since_previous",
                          "a first audit has nothing to compare against; omit it")
            if history and not has_changes:
                self.fail("latest.changes_since_previous",
                          "a re-audit must record what changed since the previous run")


def validate_initial_profile(payload: Any, label: str = "first canonical write") -> None:
    """Enforce invariants for a profile that has no trustworthy merge base."""
    problems: list[str] = []
    if not isinstance(payload, dict):
        raise ProfileInvalidError([f"{label}: payload must be an object"])
    latest = payload.get("latest")
    latest = latest if isinstance(latest, dict) else {}
    audit_id = latest.get("audit_id")

    if payload.get("history") != []:
        problems.append(f"history: {label} must start with []")
    if "changes_since_previous" in latest:
        problems.append(
            f"latest.changes_since_previous: {label} has no safe comparison base; omit it")

    for block in BLOCKS:
        value = latest.get(block)
        if value is not None and (
                not isinstance(value, dict)
                or value.get("observed_in") != audit_id):
            observed = value.get("observed_in") if isinstance(value, dict) else None
            problems.append(
                f"latest.{block}.observed_in: {label} may not carry prior state; "
                f"{observed!r} must equal this run's audit_id {audit_id!r}")

    experiments = payload.get("experiments")
    for index, experiment in enumerate(
            experiments if isinstance(experiments, list) else []):
        if not isinstance(experiment, dict):
            continue
        for field in ("created_in_audit", "last_seen_in_audit"):
            if experiment.get(field) != audit_id:
                problems.append(
                    f"experiments[{index}].{field}: {label} has no prior audit "
                    f"provenance; use this run's audit_id {audit_id!r}")

    issues = payload.get("engineering_issues")
    for index, issue in enumerate(issues if isinstance(issues, list) else []):
        if not isinstance(issue, dict):
            continue
        if issue.get("status") == "fixed":
            problems.append(
                f"engineering_issues[{index}].status: {label} may not create an "
                "issue already fixed; a newly detected issue starts open")
        if issue.get("resolved_in_audit") is not None:
            problems.append(
                f"engineering_issues[{index}].resolved_in_audit: {label} has no "
                "prior open issue to resolve; use null")
        for field in ("first_seen", "last_seen"):
            if issue.get(field) != audit_id:
                problems.append(
                    f"engineering_issues[{index}].{field}: {label} has no prior audit "
                    f"provenance; use this run's audit_id {audit_id!r}")

    if problems:
        raise ProfileInvalidError(problems)


def validate_profile(payload: Any, mode: str) -> None:
    """Raise ProfileInvalidError unless *payload* is a valid profile for *mode*."""
    if mode not in ("canonical", "recovery"):
        raise ValueError(f"unknown validation mode: {mode}")
    problems = _Validator(payload, mode).run()
    if problems:
        raise ProfileInvalidError(problems)
    if mode == "recovery":
        validate_initial_profile(payload, "recovery write")


def validate_legacy_profile(payload: Any) -> None:
    """Validate the documented 1.0 shape without inventing migration evidence.

    Schema 1.0 is structurally identical to 1.1 except for the three evidence
    fields added in 1.1. Validate a private copy with deterministic placeholders;
    the placeholders never leave this function and do not authorize a real
    issue transition.
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ProfileInvalidError(["schema_version: expected the documented legacy version '1.0'"])

    probe = copy.deepcopy(payload)
    probe["schema_version"] = SCHEMA_VERSION
    latest = probe.get("latest")
    audit_id = latest.get("audit_id") if isinstance(latest, dict) else None
    checks_run: list[str] = []
    issues = probe.get("engineering_issues")
    if isinstance(issues, list):
        for index, issue in enumerate(issues, 1):
            if not isinstance(issue, dict):
                continue
            check_id = f"legacy_issue_check_{index}"
            issue["check_id"] = check_id
            if issue.get("status") == "fixed" and issue.get("resolved_in_audit") == audit_id:
                checks_run.append(check_id)
    if isinstance(latest, dict):
        latest["engineering_checks_run"] = checks_run
        latest["engineering_checks_run_observed_in"] = audit_id
    validate_profile(probe, "canonical")


def compact_latest_snapshot(
    latest: dict[str, Any],
    engineering_issues: list[Any],
) -> dict[str, Any]:
    """Build the documented history snapshot for one canonical latest.

    ``key_metrics`` is derived deterministically from every unambiguous numeric
    leaf in the canonical metrics block. The incoming draft never chooses what
    prior values survive demotion.
    """
    audit_id = latest.get("audit_id")
    measured = {
        block: (
            isinstance(latest.get(block), dict)
            and latest[block].get("observed_in") == audit_id
        )
        for block in BLOCKS
    }

    layers = latest.get("data_layers")
    compact_layers: dict[str, Any] = {}
    for name in ("ga4", "gsc", "session_replay"):
        layer = layers.get(name) if isinstance(layers, dict) else None
        compact_layers[name] = layer.get("available") if isinstance(layer, dict) else None

    page_snapshot = None
    current_snapshot = latest.get("page_snapshot")
    if measured["page_snapshot"] and isinstance(current_snapshot, dict):
        primary_cta = current_snapshot.get("primary_cta")
        page_snapshot = {
            "headline": current_snapshot.get("headline"),
            "primary_cta_text": (
                primary_cta.get("text") if isinstance(primary_cta, dict)
                else current_snapshot.get("primary_cta_text")
            ),
        }

    compact_lift = None
    current_lift = latest.get("lift")
    if measured["lift"] and isinstance(current_lift, dict):
        factors = current_lift.get("factors")
        compact_lift = {
            "total": current_lift.get("total"),
            "basis": current_lift.get("basis"),
            "factors": {
                name: (
                    factor.get("score") if isinstance(factor, dict) else None
                )
                for name, factor in (
                    factors.items() if isinstance(factors, dict) else ()
                )
            },
        }

    compact_pxl = None
    current_pxl = latest.get("pxl")
    if measured["pxl"] and isinstance(current_pxl, dict):
        ideas = current_pxl.get("ideas")
        ranked = sorted(
            (
                idea for idea in ideas
                if isinstance(ideas, list)
                and isinstance(idea, dict)
                and is_int(idea.get("rank"))
                and isinstance(idea.get("experiment_id"), str)
            ),
            key=lambda idea: idea["rank"],
        ) if isinstance(ideas, list) else []
        compact_pxl = {
            "scoring_mode": current_pxl.get("scoring_mode"),
            "top_3": [idea["experiment_id"] for idea in ranked[:3]],
        }

    key_metrics = None
    current_metrics = latest.get("metrics")
    if measured["metrics"] and isinstance(current_metrics, dict):
        metric_names = _Validator.key_metric_names(current_metrics)
        key_metrics = {
            name: _Validator.find_metric(current_metrics, name)
            for name in metric_names
        }

    open_sev0_count = sum(
        1 for issue in engineering_issues
        if isinstance(issue, dict)
        and issue.get("status") == "open"
        and issue.get("severity") == "Sev0"
    )

    return {
        "audit_id": audit_id,
        "audited_at": latest.get("audited_at"),
        "scope": latest.get("scope"),
        "measured": measured,
        "date_range": latest.get("date_range"),
        "data_layers": compact_layers,
        "page_snapshot": page_snapshot,
        "lift": compact_lift,
        "pxl": compact_pxl,
        "key_metrics": key_metrics,
        "open_sev0_count": open_sev0_count,
    }


def validate_transition(existing: dict[str, Any], payload: dict[str, Any]) -> None:
    """Validate state changes that require the locked canonical profile as evidence."""
    problems: list[str] = []
    old_page = existing.get("page") if isinstance(existing.get("page"), dict) else {}
    new_page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
    stable_identity = {
        "target": lambda value: value,
        "host": lambda value: value.lower() if isinstance(value, str) else value,
        "path": lambda value: normalized_page_path(value) if isinstance(value, str) else value,
        "slug": lambda value: value,
    }
    for field, normalize in stable_identity.items():
        if normalize(new_page.get(field)) != normalize(old_page.get(field)):
            problems.append(
                f"page.{field}: canonical page identity is stable across re-audits; "
                f"preserve {old_page.get(field)!r}, not {new_page.get(field)!r}. "
                "Handle a real URL move by migrating the canonical profile first."
            )

    old_latest = existing.get("latest") if isinstance(existing.get("latest"), dict) else {}
    new_latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else {}
    old_audit_id = old_latest.get("audit_id")
    new_audit_id = new_latest.get("audit_id")

    # A focused run may replace only blocks it actually measured. Any block
    # whose observed_in is not this run's audit id is carried state and must be
    # byte-for-byte equal to the locked canonical latest; otherwise a draft can
    # rewrite or erase stale data while correctly emitting no deltas for it.
    for block in BLOCKS:
        prior_block = old_latest.get(block)
        current_block = new_latest.get(block)
        measured_now = (
            isinstance(current_block, dict)
            and current_block.get("observed_in") == new_audit_id
        )
        if not measured_now and not exact_json_equal(current_block, prior_block):
            problems.append(
                f"latest.{block}: a block not measured in {new_audit_id!r} must "
                "exactly preserve the locked canonical value; carried state may "
                "not be changed or deleted")

    history = payload.get("history")
    if isinstance(old_audit_id, str) and isinstance(new_audit_id, str):
        if old_audit_id == new_audit_id:
            problems.append(
                "latest.audit_id: a re-audit must mint a new audit id; "
                f"{new_audit_id!r} is already the canonical latest")
        elif (not isinstance(history, list) or not history
              or not isinstance(history[0], dict)
              or history[0].get("audit_id") != old_audit_id):
            problems.append(
                "history[0].audit_id: the previous canonical latest "
                f"{old_audit_id!r} must be demoted at the head of history")
        else:
            head = history[0]
            expected_head = compact_latest_snapshot(
                old_latest,
                existing.get("engineering_issues", []),
            )
            expected_key_metrics = expected_head.get("key_metrics")
            if (isinstance(expected_key_metrics, dict)
                    and any(value is None for value in expected_key_metrics.values())):
                problems.append(
                    "history[0].key_metrics: every selected compact metric must "
                    "resolve unambiguously to a numeric value in the locked "
                    "canonical latest.metrics")
            if not exact_json_equal(head, expected_head):
                problems.append(
                    "history[0]: must be the exact compact snapshot derived from "
                    "the locked canonical latest; source values may not be "
                    "rewritten before computing deltas")

            old_history = existing.get("history")
            expected_tail = old_history[:11] if isinstance(old_history, list) else []
            if not exact_json_equal(history[1:], expected_tail):
                problems.append(
                    "history[1:]: must preserve the locked canonical history tail "
                    "exactly, retaining the newest 11 snapshots after demotion")

    old_experiments = {
        experiment.get("id"): experiment
        for experiment in existing.get("experiments", [])
        if isinstance(experiment, dict) and isinstance(experiment.get("id"), str)
    }
    new_experiments = {
        experiment.get("id"): experiment
        for experiment in payload.get("experiments", [])
        if isinstance(experiment, dict) and isinstance(experiment.get("id"), str)
    }
    current_pxl = new_latest.get("pxl")
    current_ideas = (
        current_pxl.get("ideas", [])
        if isinstance(current_pxl, dict)
        and current_pxl.get("observed_in") == new_audit_id
        else []
    )
    ranked_ids = {
        idea.get("experiment_id")
        for idea in current_ideas
        if isinstance(idea, dict) and isinstance(idea.get("experiment_id"), str)
    }
    for experiment_id, prior in old_experiments.items():
        current = new_experiments.get(experiment_id)
        if current is None:
            problems.append(
                f"experiments[{experiment_id}]: prior longitudinal record may not be deleted")
            continue
        for field in ("created_in_audit", "element_type", "primary_metric"):
            if current.get(field) != prior.get(field):
                problems.append(
                    f"experiments[{experiment_id}].{field}: must preserve "
                    f"{prior.get(field)!r}, not {current.get(field)!r}")
        if prior.get("status_source") == "user_reported":
            if current.get("status_source") != "user_reported":
                problems.append(
                    f"experiments[{experiment_id}].status_source: a user-reported "
                    "record may never revert to audit ownership")
            if prior.get("outcome") is not None and current.get("outcome") is None:
                problems.append(
                    f"experiments[{experiment_id}].outcome: a recorded outcome "
                    "may not be erased")
        if prior.get("hypothesis_doc_emitted") is True and (
                current.get("hypothesis_doc_emitted") is not True):
            problems.append(
                f"experiments[{experiment_id}].hypothesis_doc_emitted: a recorded "
                "document emission may not be erased")
        if experiment_id in ranked_ids:
            if current.get("last_seen_in_audit") != new_audit_id:
                problems.append(
                    f"experiments[{experiment_id}].last_seen_in_audit: an idea "
                    f"ranked this run must be stamped {new_audit_id!r}")
        else:
            if current.get("last_seen_in_audit") != prior.get("last_seen_in_audit"):
                problems.append(
                    f"experiments[{experiment_id}].last_seen_in_audit: an unranked "
                    "experiment was not re-observed and must preserve its prior stamp")
            for field in ("name", "hypothesis"):
                if current.get(field) != prior.get(field):
                    problems.append(
                        f"experiments[{experiment_id}].{field}: an unranked experiment "
                        "may receive a user-reported state update, but its audit-owned "
                        "definition may not be rewritten")
            if current.get("status_source") == "audit":
                for field in ("status", "outcome"):
                    if current.get(field) != prior.get(field):
                        problems.append(
                            f"experiments[{experiment_id}].{field}: an unranked "
                            "audit-owned experiment must preserve its prior state")

    for experiment_id, current in new_experiments.items():
        if experiment_id in old_experiments:
            continue
        if experiment_id not in ranked_ids:
            problems.append(
                f"experiments[{experiment_id}]: a new longitudinal experiment must "
                "come from this run's PXL ranking")
        if current.get("created_in_audit") != new_audit_id:
            problems.append(
                f"experiments[{experiment_id}].created_in_audit: a new experiment "
                f"must be stamped {new_audit_id!r}")
        if current.get("last_seen_in_audit") != new_audit_id:
            problems.append(
                f"experiments[{experiment_id}].last_seen_in_audit: a new experiment "
                f"must be stamped {new_audit_id!r}")

    old_issues = {
        issue.get("id"): issue
        for issue in existing.get("engineering_issues", [])
        if isinstance(issue, dict) and isinstance(issue.get("id"), str)
    }
    new_issues = {
        issue.get("id"): issue
        for issue in payload.get("engineering_issues", [])
        if isinstance(issue, dict) and isinstance(issue.get("id"), str)
    }
    checks_run = new_latest.get("engineering_checks_run")
    checks_run = set(checks_run) if isinstance(checks_run, list) else set()
    legacy_issues = existing.get("schema_version") == "1.0"
    for issue_id, prior in old_issues.items():
        issue = new_issues.get(issue_id)
        if issue is None:
            problems.append(
                f"engineering_issues[{issue_id}]: prior longitudinal record may not be deleted")
            continue
        status = issue.get("status")
        resolved = issue.get("resolved_in_audit")
        check_id = issue.get("check_id")
        prior_check_id = prior.get("check_id")
        legacy_without_check = legacy_issues and prior_check_id is None
        if not legacy_without_check and check_id != prior_check_id:
            problems.append(
                f"engineering_issues[{issue_id}].check_id: stable detecting check "
                f"must remain {prior_check_id!r}, not {check_id!r}")
        if issue.get("first_seen") != prior.get("first_seen"):
            problems.append(
                f"engineering_issues[{issue_id}].first_seen: must preserve "
                f"{prior.get('first_seen')!r}")
        prior_status = prior.get("status")
        if prior_status == "open" and status == "fixed":
            if legacy_without_check:
                problems.append(
                    f"engineering_issues[{issue_id}].status: a schema 1.0 issue "
                    "must remain open during migration because the prior profile "
                    "cannot prove which detecting check ran")
            if resolved != new_audit_id:
                problems.append(
                    f"engineering_issues[{issue_id}].resolved_in_audit: an open issue "
                    f"may become fixed only in this run {new_audit_id!r}, not {resolved!r}")
            if not legacy_without_check and prior_check_id not in checks_run:
                problems.append(
                    f"engineering_issues[{issue_id}].status: open -> fixed requires "
                    f"its prior exact check {prior_check_id!r} in this run's "
                    "engineering_checks_run")
            if issue.get("last_seen") != prior.get("last_seen"):
                problems.append(
                    f"engineering_issues[{issue_id}].last_seen: a check that no longer "
                    "detects the issue preserves the last audit that did")
        elif prior_status == "fixed" and status == "fixed":
            prior_resolved = prior.get("resolved_in_audit")
            if resolved != prior_resolved:
                problems.append(
                    f"engineering_issues[{issue_id}].resolved_in_audit: an already-fixed "
                    f"issue must preserve {prior_resolved!r}, not rewrite it as {resolved!r}")
        elif prior_status == "fixed" and status == "open":
            if not legacy_without_check and prior_check_id not in checks_run:
                problems.append(
                    f"engineering_issues[{issue_id}].status: reopening a fixed issue "
                    f"requires its exact check {prior_check_id!r} in this run")
            if issue.get("last_seen") != new_audit_id:
                problems.append(
                    f"engineering_issues[{issue_id}].last_seen: a re-detected issue "
                    f"must be stamped {new_audit_id!r}")
        elif (prior_status == "open" and status == "open"
              and issue.get("last_seen") == new_audit_id
              and not legacy_without_check
              and prior_check_id not in checks_run):
            problems.append(
                f"engineering_issues[{issue_id}].last_seen: advancing the stamp "
                f"requires its exact check {prior_check_id!r} in this run")

        last_seen = issue.get("last_seen")
        if last_seen not in (prior.get("last_seen"), new_audit_id):
            problems.append(
                f"engineering_issues[{issue_id}].last_seen: must preserve "
                f"{prior.get('last_seen')!r} or advance to {new_audit_id!r}")

    for issue_id, issue in new_issues.items():
        if issue_id in old_issues:
            continue
        if issue.get("status") == "fixed":
            problems.append(
                f"engineering_issues[{issue_id}].status: a newly detected issue "
                "cannot be created as fixed")
        if issue.get("first_seen") != new_audit_id:
            problems.append(
                f"engineering_issues[{issue_id}].first_seen: a new issue must be "
                f"stamped {new_audit_id!r}")
        if issue.get("last_seen") != new_audit_id:
            problems.append(
                f"engineering_issues[{issue_id}].last_seen: a new issue must be "
                f"stamped {new_audit_id!r}")
    if problems:
        raise ProfileInvalidError(problems)


# ── filesystem ────────────────────────────────────────────────────────────────

def fingerprint(path: Path) -> str:
    """Return a stable fingerprint for *path*, or MISSING when absent."""
    if not path.exists():
        return MISSING
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_payload(path: Path, mode: str) -> dict[str, Any]:
    """Load *path* and fully validate it for *mode* before it can be written."""
    value = json.loads(path.read_text())
    validate_profile(value, mode)
    assert_not_future(value)
    return value


def encoded_payload(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def fsync_directory(path: Path) -> None:
    """Best-effort directory fsync so a completed rename survives a crash."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def assert_replaceable(canonical: Path) -> dict[str, Any] | None:
    """Refuse to replace a canonical profile this writer cannot safely supersede.

    Read under the caller's lock, never from the audit's earlier read: a
    fingerprint match proves the file is unchanged, not that it is a version we
    are allowed to downgrade. An unparseable or newer-schema canonical must go
    down the recovery path instead.
    """
    if not canonical.exists():
        return None
    try:
        existing = json.loads(canonical.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProfileVersionError(
            f"canonical profile is not parseable ({exc}); it must be preserved and "
            "written beside with `recovery --kind corrupt`, never replaced"
        ) from exc
    if not isinstance(existing, dict):
        raise ProfileVersionError(
            "canonical profile is not a JSON object; use `recovery --kind corrupt`"
        )
    found = existing.get("schema_version")
    if not isinstance(found, str) or not VERSION_RE.match(found):
        raise ProfileVersionError(
            f"canonical profile has an unusable schema_version ({found!r}); "
            "use `recovery --kind corrupt`"
        )
    if version_tuple(found) > version_tuple(SCHEMA_VERSION):
        raise ProfileVersionError(
            f"canonical profile is schema {found}, newer than the {SCHEMA_VERSION} this "
            "writer emits; replacing it would strip fields the newer schema added — "
            "use `recovery --kind unsupported-version`"
        )
    if found != SCHEMA_VERSION and found not in SUPPORTED_LEGACY_VERSIONS:
        raise ProfileVersionError(
            f"canonical profile uses unrecognized older schema {found!r}; only "
            f"{sorted(SUPPORTED_LEGACY_VERSIONS)!r} can be migrated safely. "
            "Preserve it with `recovery --kind corrupt` instead of overwriting it"
        )
    try:
        if found == SCHEMA_VERSION:
            validate_profile(existing, "canonical")
        else:
            validate_legacy_profile(existing)
    except ProfileInvalidError as exc:
        label = "legacy " if found != SCHEMA_VERSION else ""
        raise ProfileVersionError(
            f"canonical {label}profile is structurally or semantically invalid; it must be "
            "preserved and written beside with `recovery --kind corrupt`: "
            + "; ".join(exc.problems)
        ) from exc
    return existing


def atomic_canonical_write(
    canonical: Path,
    payload: dict[str, Any],
    expected_fingerprint: str,
    today: dt.date | None = None,
) -> Path:
    """Write *payload* only if *canonical* still matches the audited base."""
    validate_profile(payload, "canonical")
    assert_not_future(payload, today)
    assert_payload_matches_target(canonical, payload)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    lock_path = canonical.with_name(f".{canonical.name}.lock")

    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        current = fingerprint(canonical)
        if current != expected_fingerprint:
            raise ProfileConflictError(
                "canonical profile changed during the audit "
                f"(expected {expected_fingerprint}, found {current}); reread, remerge, and retry"
            )
        # Both guards run under the same lock, so neither can be raced.
        existing = assert_replaceable(canonical)
        if existing is not None:
            validate_transition(existing, payload)
        else:
            validate_initial_profile(payload)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{canonical.name}.",
            suffix=".tmp",
            dir=str(canonical.parent),
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded_payload(payload))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, canonical)
            fsync_directory(canonical.parent)
        finally:
            if temporary.exists():
                temporary.unlink()

    return canonical


def atomic_recovery_write(
    canonical: Path,
    payload: dict[str, Any],
    kind: str,
    now: dt.datetime | None = None,
    today: dt.date | None = None,
) -> Path:
    """Create a unique recovery file without reading or changing *canonical*."""
    if kind not in RECOVERY_KINDS:
        raise ValueError(f"unsupported recovery kind: {kind}")

    validate_profile(payload, "recovery")
    assert_not_future(payload, today)
    # The recovery filename is derived from the canonical stem, so a mismatched
    # payload would file this run's findings beside the wrong page.
    assert_payload_matches_target(canonical, payload)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    timestamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    stem = canonical.stem
    data = encoded_payload(payload)

    suffix = 1
    while True:
        ordinal = "" if suffix == 1 else f"-{suffix}"
        recovery = canonical.with_name(f"{stem}.{kind}-{timestamp}{ordinal}.json")
        try:
            descriptor = os.open(
                recovery,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
        except FileExistsError:
            suffix += 1
            continue

        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(canonical.parent)
        except BaseException:
            recovery.unlink(missing_ok=True)
            raise
        return recovery


# ── cli ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fingerprint_parser = subparsers.add_parser("fingerprint")
    fingerprint_parser.add_argument("canonical", type=Path)

    validate_parser = subparsers.add_parser(
        "validate", help="check a draft without writing anything")
    validate_parser.add_argument("--payload", type=Path, required=True)
    validate_parser.add_argument("--mode", choices=("canonical", "recovery"), default="canonical")

    write_parser = subparsers.add_parser("write")
    write_parser.add_argument("--canonical", type=Path, required=True)
    write_parser.add_argument("--payload", type=Path, required=True)
    write_parser.add_argument("--expected-fingerprint", required=True)

    recovery_parser = subparsers.add_parser("recovery")
    recovery_parser.add_argument("--canonical", type=Path, required=True)
    recovery_parser.add_argument("--payload", type=Path, required=True)
    recovery_parser.add_argument("--kind", choices=sorted(RECOVERY_KINDS), required=True)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "fingerprint":
            print(fingerprint(args.canonical))
            return 0

        mode = "recovery" if args.command == "recovery" else getattr(args, "mode", "canonical")
        payload = load_payload(args.payload, mode)
        if args.command == "validate":
            print(f"OK: valid {mode} profile")
            return 0
        if args.command == "write":
            written = atomic_canonical_write(
                args.canonical,
                payload,
                args.expected_fingerprint,
            )
        else:
            written = atomic_recovery_write(args.canonical, payload, args.kind)
        print(written)
        return 0
    except ProfileConflictError as exc:
        print(f"CONFLICT: {exc}", file=sys.stderr)
        return 3
    except ProfileVersionError as exc:
        print(f"VERSION: {exc}", file=sys.stderr)
        return 4
    except ProfileInvalidError as exc:
        print("INVALID: payload rejected —", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
