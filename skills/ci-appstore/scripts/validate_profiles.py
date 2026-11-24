#!/usr/bin/env python3
"""Validate competitor profiles against the CI platform schema.

Checks, per profile in profiles/*.json:
  1. Envelope conforms to schema/competitor.schema.json.
  2. Each present layer conforms to its registered layer schema (schema/layers/<id>.schema.json).
  3. layers_populated matches the actual keys of `layers`.
  4. Provenance integrity: current layers have current claims, current claim paths
     resolve, and layer ownership/version metadata matches the registry.
  5. Staleness: current claims older than refresh.stale_after_days fail validation
     until they are re-fetched or marked stale. Use --owner to scope this check.

Exit code 0 if all profiles are valid (warnings allowed), 1 if any hard error.

Usage:
  python3 scripts/validate_profiles.py                          # all profiles in the skill folder
  python3 scripts/validate_profiles.py --data-dir examples/demo --today 2026-09-15
  python3 scripts/validate_profiles.py --owner ci-appstore
  python3 scripts/validate_profiles.py path/to/profiles/acme-reviews.json
"""
import argparse
import json
import sys
import datetime
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SKILL_DIR / "schema"

try:
    import jsonschema
except ImportError:
    jsonschema = None


def load_json(p):
    with open(p) as f:
        return json.load(f)


def read_config_stale_days(config, default=90):
    """Tiny YAML sniff — avoids a hard PyYAML dependency for one integer."""
    if not config.exists():
        return default
    for line in config.read_text().splitlines():
        s = line.strip()
        if s.startswith("stale_after_days:"):
            try:
                return int(s.split(":", 1)[1].strip().split("#")[0])
            except ValueError:
                return default
    return default


def registry_layers():
    reg = load_json(SCHEMA_DIR / "layers" / "registry.json")
    return {layer["id"]: layer for layer in reg["layers"]}


def registry_layer_schemas(registry):
    out = {}
    for layer in registry.values():
        if layer.get("schema"):
            out[layer["id"]] = SKILL_DIR / layer["schema"]
    return out


def validate_schema(instance, schema, label, errors):
    validator = jsonschema.Draft7Validator(schema)
    for e in sorted(validator.iter_errors(instance), key=lambda e: e.path):
        loc = ".".join(str(x) for x in e.path) or "(root)"
        errors.append(f"    [schema:{label}] {loc}: {e.message}")


FIELD_TOKEN = re.compile(r"([^.[\]]+)|\[(\d+)\]")


def field_exists(profile, field):
    value = profile
    for name, index in FIELD_TOKEN.findall(field):
        key = int(index) if index else name
        try:
            value = value[key]
        except (KeyError, IndexError, TypeError):
            return False
    return True


def check_profile(path, envelope_schema, registry, layer_schemas, stale_days, freshness_owner=None,
                  today=None):
    errors, warnings = [], []
    prof = load_json(path)
    if prof.get("slug") != Path(path).stem:
        errors.append(f"    slug {prof.get('slug')!r} does not match filename {Path(path).name!r}")

    validate_schema(prof, envelope_schema, "envelope", errors)

    layers = prof.get("layers", {})
    populated = set(prof.get("layers_populated", []))
    if populated != set(layers.keys()):
        errors.append(
            f"    layers_populated {sorted(populated)} != layers keys {sorted(layers.keys())}"
        )

    for lid, ldata in layers.items():
        registered = registry.get(lid)
        if registered is None:
            errors.append(f"    layer '{lid}' is not registered")
        elif registered.get("status") != "active":
            errors.append(f"    layer '{lid}' is populated but registry status is not 'active'")
        else:
            meta = ldata.get("meta", {})
            expected = {
                "layer_id": lid,
                "collected_by": registered.get("owner_skill"),
                "layer_version": registered.get("layer_version"),
            }
            for key, wanted in expected.items():
                if meta.get(key) != wanted:
                    errors.append(
                        f"    layer '{lid}' meta.{key} {meta.get(key)!r} != registry {wanted!r}"
                    )

        if lid in layer_schemas and layer_schemas[lid].exists():
            validate_schema(ldata, load_json(layer_schemas[lid]), f"layer:{lid}", errors)
        else:
            warnings.append(f"    layer '{lid}' has no registered schema — envelope-only validation")

    # Provenance coverage
    claims = prof.get("claims", [])
    current_claims = [c for c in claims if c.get("verification") in {"verified", "unverified"}]
    current_claimed_fields = {c.get("field", "") for c in current_claims}
    for claim in claims:
        field = claim.get("field")
        if not isinstance(field, str):
            continue
        current = claim.get("verification") in {"verified", "unverified"}
        if not field_exists(prof, field):
            target = errors if current else warnings
            target.append(f"    claim field does not resolve: {field!r}")
        layer = claim.get("layer")
        tokens = FIELD_TOKEN.findall(field)
        field_layer = tokens[1][0] if len(tokens) > 1 and tokens[0][0] == "layers" else None
        if current and layer != field_layer:
            errors.append(f"    claim layer {layer!r} does not match field {field!r}")
        elif current and field_layer is not None and field_layer not in layers:
            errors.append(f"    current claim targets absent layer '{field_layer}': {field!r}")

    # Generic rule (any layer, any skill): a current layer with ZERO current claims
    # tagged to it is unverifiable by construction — hard error, not a warning.
    current_claim_layers = {c.get("layer") for c in current_claims}
    for lid, ldata in layers.items():
        if ldata.get("meta", {}).get("status") != "stale" and lid not in current_claim_layers:
            errors.append(
                f"    layer '{lid}' is current but has no verified/unverified claims tagged "
                f"layer='{lid}' — register current load-bearing facts in the claims ledger"
            )
    if "app_store" in layers:
        pricing = layers["app_store"].get("pricing", {})
        if pricing.get("tiers") and not any(
            f.startswith("layers.app_store.pricing") for f in current_claimed_fields
        ):
            errors.append("    app_store pricing present but no current pricing claim in ledger")
        if layers["app_store"].get("reviews", {}).get("count") is not None and not any(
            f.startswith("layers.app_store.reviews") for f in current_claimed_fields
        ):
            errors.append("    app_store reviews present but no current reviews claim in ledger")
    if prof.get("scores") and not any(f.startswith("scores") for f in current_claimed_fields):
        errors.append("    scores present but no current scores claim (mark them analyst_inference)")

    # Staleness
    today = today or datetime.date.today()
    stale = 0
    freshness_claims = current_claims
    if freshness_owner:
        freshness_claims = [
            c for c in current_claims
            if registry.get(c.get("layer"), {}).get("owner_skill") == freshness_owner
        ]
    for c in freshness_claims:
        f = c.get("fetched")
        if not f:
            continue
        try:
            d = datetime.date.fromisoformat(f)
        except ValueError:
            warnings.append(f"    claim has non-ISO fetched date: {f!r}")
            continue
        age = (today - d).days
        if age > stale_days:
            stale += 1
    if stale:
        errors.append(
            f"    {stale} current claim(s) older than {stale_days}d — re-fetch or mark stale"
        )

    return errors, warnings


def main():
    if jsonschema is None:
        print("ERROR: `jsonschema` is required for full profile validation.")
        print("       Install with:  pip install jsonschema pyyaml")
        return 1

    envelope_schema = load_json(SCHEMA_DIR / "competitor.schema.json")
    registry = registry_layers()
    layer_schemas = registry_layer_schemas(registry)

    parser = argparse.ArgumentParser(description="Validate competitor profiles against the schema.")
    parser.add_argument("--data-dir", default=str(SKILL_DIR),
                        help="folder holding config/ and profiles/ (default: the skill folder)")
    parser.add_argument("--today", type=datetime.date.fromisoformat,
                        help="YYYY-MM-DD to measure claim age against (default: today); "
                             "use it to re-check a dated snapshot such as the demo")
    parser.add_argument(
        "--owner",
        choices=sorted({layer["owner_skill"] for layer in registry.values()}),
        help="only enforce claim freshness for layers owned by this skill",
    )
    parser.add_argument("profiles", nargs="*")
    args = parser.parse_args()
    data_dir = Path(args.data_dir).resolve()
    stale_days = read_config_stale_days(data_dir / "config" / "competitors.yaml")
    profiles_dir = data_dir / "profiles"
    paths = [Path(p) for p in args.profiles] if args.profiles else sorted(profiles_dir.glob("*.json"))
    if not paths:
        print("No profiles found in", profiles_dir)
        return 0

    total_err = 0
    for p in paths:
        errors, warnings = check_profile(
            p, envelope_schema, registry, layer_schemas, stale_days, args.owner, args.today
        )
        status = "FAIL" if errors else ("warn" if warnings else "ok")
        print(f"[{status:4}] {p.name}")
        for e in errors:
            print(e)
        for w in warnings:
            print(w)
        total_err += len(errors)

    print()
    if total_err:
        print(f"✗ {total_err} error(s) across {len(paths)} profile(s).")
        return 1
    print(f"✓ {len(paths)} profile(s) valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
