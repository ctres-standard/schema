#!/usr/bin/env python3
"""Validate the CTRES v1.0 JSON Schema package.

Checks, in order:

1. Every file under schema/ is a valid JSON Schema (draft 2020-12) document whose $id
   lies under https://ctres.org/schema/1.0/ and matches its path.
2. Every property definition carries a description that cites a section of the
   Standard, and an x-ctres-req annotation (M, C or O); C fields also carry
   x-ctres-condition.
3. Every example under examples/ validates against its schema.
4. Deliberately broken copies of the examples fail validation, and a few deliberate
   variations (for example not_recorded in place of a timestamp) still pass.

The only dependency is the 'jsonschema' package, which brings 'referencing'.
$ref across files is resolved from a local registry; nothing is fetched.

Usage:  python tests/validate_examples.py
Exit status is 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
EXAMPLE_DIR = ROOT / "examples"
BASE_ID = "https://ctres.org/schema/1.0/"

# Composition keywords whose subschemas restate or condition fields defined elsewhere;
# field annotations are required where a field is defined, not where it is re-constrained.
NOT_FIELD_DEFINITIONS = {"allOf", "anyOf", "oneOf", "not", "if", "then", "else", "dependentSchemas"}

failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)
    print(f"  FAIL  {message}")


def ok(message: str) -> None:
    print(f"  ok    {message}")


# ---------------------------------------------------------------------------------------------
# Load schemas and build the registry
# ---------------------------------------------------------------------------------------------
def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


schema_files = sorted(SCHEMA_DIR.rglob("*.schema.json"))
schemas: dict[Path, dict] = {p: load_json(p) for p in schema_files}
registry: Registry = Registry().with_resources(
    (s["$id"], Resource(contents=s, specification=DRAFT202012)) for s in schemas.values()
)


def validator_for(schema_path: Path) -> Draft202012Validator:
    return Draft202012Validator(
        schemas[schema_path], registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER
    )


# ---------------------------------------------------------------------------------------------
# 1. Schemas are valid and identified
# ---------------------------------------------------------------------------------------------
print("1. Schemas")
for path, schema in schemas.items():
    rel = path.relative_to(SCHEMA_DIR).as_posix()
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # noqa: BLE001
        fail(f"{rel}: not a valid draft 2020-12 schema: {exc}")
        continue
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        fail(f"{rel}: $schema is not draft 2020-12")
    elif schema.get("$id") != BASE_ID + rel:
        fail(f"{rel}: $id {schema.get('$id')!r} does not match {BASE_ID + rel!r}")
    else:
        ok(rel)

# ---------------------------------------------------------------------------------------------
# 2. Field annotations
# ---------------------------------------------------------------------------------------------
print("2. Field annotations (description with section reference; x-ctres-req; x-ctres-condition)")


def lint(node: Any, where: str, problems: list[str]) -> int:
    count = 0
    if isinstance(node, list):
        for i, item in enumerate(node):
            count += lint(item, f"{where}/{i}", problems)
        return count
    if not isinstance(node, dict):
        return 0
    props = node.get("properties")
    if isinstance(props, dict):
        for name, sub in props.items():
            at = f"{where}/properties/{name}"
            count += 1
            if not isinstance(sub, dict):
                problems.append(f"{at}: field definition is not an object")
                continue
            desc = sub.get("description", "")
            if not desc or ("§" not in desc and "Annex" not in desc):
                problems.append(f"{at}: description missing or cites no section")
            req = sub.get("x-ctres-req")
            if req not in ("M", "C", "O"):
                problems.append(f"{at}: x-ctres-req missing or not M, C or O")
            if req == "C" and not sub.get("x-ctres-condition"):
                problems.append(f"{at}: C field without x-ctres-condition")
            if req != "C" and "x-ctres-condition" in sub:
                problems.append(f"{at}: x-ctres-condition on a field that is not C")
            count += lint(sub, at, problems)
    for key, value in node.items():
        if key in NOT_FIELD_DEFINITIONS or key == "properties":
            continue
        if isinstance(value, (dict, list)):
            count += lint(value, f"{where}/{key}", problems)
    return count


for path, schema in schemas.items():
    rel = path.relative_to(SCHEMA_DIR).as_posix()
    problems: list[str] = []
    n = lint(schema, rel, problems)
    if problems:
        for p in problems:
            fail(p)
    else:
        ok(f"{rel}: {n} field definitions annotated")

# ---------------------------------------------------------------------------------------------
# 3. Examples validate
# ---------------------------------------------------------------------------------------------
print("3. Examples")


def schema_path_for(example_name: str) -> Path:
    if example_name.startswith("manifest"):
        return SCHEMA_DIR / "manifest.schema.json"
    if example_name.startswith("profile"):
        return SCHEMA_DIR / "profile.schema.json"
    m = re.search(r"(?:^|-)r(\d{2})-", example_name)
    if not m:
        raise LookupError(f"cannot tell which schema applies to {example_name}")
    matches = sorted((SCHEMA_DIR / "records").glob(f"r{m.group(1)}_*.schema.json"))
    if len(matches) != 1:
        raise LookupError(f"expected one record schema for {example_name}, found {len(matches)}")
    return matches[0]


def errors_of(instance: Any, schema_path: Path) -> list[str]:
    v = validator_for(schema_path)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in v.iter_errors(instance)]


examples: dict[str, Any] = {}
example_files = sorted(EXAMPLE_DIR.glob("*.json"))
if not example_files:
    fail("no examples found")
for path in example_files:
    instance = load_json(path)
    examples[path.name] = instance
    try:
        sp = schema_path_for(path.name)
    except LookupError as exc:
        fail(str(exc))
        continue
    errs = errors_of(instance, sp)
    if errs:
        fail(f"{path.name} against {sp.relative_to(SCHEMA_DIR).as_posix()}:")
        for e in errs:
            print(f"          {e}")
    else:
        ok(f"{path.name}  ->  {sp.relative_to(SCHEMA_DIR).as_posix()}")

# Every record type, the manifest and the profile have at least one example.
covered = {schema_path_for(n).name for n in examples}
for sp in schema_files:
    if sp.parent.name == "records" or sp.name in ("manifest.schema.json", "profile.schema.json"):
        if sp.name not in covered:
            fail(f"no example for {sp.relative_to(SCHEMA_DIR).as_posix()}")

# ---------------------------------------------------------------------------------------------
# 4. Broken copies fail, deliberate variations pass
# ---------------------------------------------------------------------------------------------
print("4. Deliberately broken copies (must fail) and variations (must pass)")


def drop(*path: Any) -> Callable[[Any], None]:
    def f(d: Any) -> None:
        for k in path[:-1]:
            d = d[k]
        del d[path[-1]]
    return f


def put(value: Any, *path: Any) -> Callable[[Any], None]:
    def f(d: Any) -> None:
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = value
    return f


def both(*fns: Callable[[Any], None]) -> Callable[[Any], None]:
    def f(d: Any) -> None:
        for fn in fns:
            fn(d)
    return f


CARD = "annex-c-r03-card-deposit.json"
MM = "annex-c-r03-mobile-money-deposit.json"
VA = "annex-c-r03-virtual-asset-pooled-deposit.json"
WD = "annex-c-r04-instant-payment-withdrawal.json"
COV = "annex-c-r07-coverage-statement.json"
R04 = SCHEMA_DIR / "records" / "r04_withdrawal.schema.json"

# (description, example, mutation, expected_valid, schema override)
CASES: list[tuple[str, str, Callable[[Any], None], bool, Path | None]] = [
    # R3 / R4
    ("R3 without tx_id", CARD, drop("tx_id"), False, None),
    ("R3 amount as a JSON number", CARD, put(150.0, "amount"), False, None),
    ("R3 amount with a decimal comma", CARD, put("150,00", "amount"), False, None),
    ("R3 timestamp without offset", CARD, put("2026-11-04T19:02:11", "initiated_at"), False, None),
    ("R3 rail outside the enumeration", CARD, put("cheque", "rail"), False, None),
    ("R3 with an undefined field", CARD, put("blue", "colour"), False, None),
    ("R3 card payment carrying a virtual-asset field", CARD, put("0xabc", "tx_hash"), False, None),
    ("R3 deposit carrying a withdrawal-only field", CARD, put("2026-11-04T19:02:11+01:00", "requested_at"), False, None),
    ("R3 deposit validated as R4", CARD, lambda d: None, False, R04),
    ("R3 check_ids with an invented gap marker", CARD, put("none", "check_ids"), False, None),
    ("R3 credited_at with an invented gap marker", CARD, put("unknown", "credited_at"), False, None),
    ("R3 player_ref without player_ref_scope", CARD, drop("player_ref_scope"), False, None),
    ("R3 fees without the network component", CARD, drop("fees", "network"), False, None),
    ("R3 tax line with rate as a JSON number", MM, put(0.05, "tax_lines", 0, "rate"), False, None),
    ("R3 empty tax_lines", MM, put([], "tax_lines"), False, None),
    ("R3 virtual asset on chain without tx_hash", VA, put(False, "off_chain_movement"), False, None),
    ("R3 virtual asset without chain", VA, drop("chain"), False, None),
    ("R4 without paid_at", WD, drop("paid_at"), False, None),
    ("R4 without approved_by", WD, drop("approved_by"), False, None),
    ("R4 same_instrument without source_instrument_ids", WD, drop("source_instrument_ids"), False, None),
    ("R4 destination_rule outside the enumeration", WD, put("anywhere", "destination_rule"), False, None),
    ("R3 check_ids not_recorded (visible gap)", CARD, put("not_recorded", "check_ids"), True, None),
    ("R3 credited_at not_recorded (visible gap)", CARD, put("not_recorded", "credited_at"), True, None),
    ("R3 empty check_ids (no check applied)", CARD, put([], "check_ids"), True, None),
    ("R4 profile_route without source_instrument_ids", WD, both(put("profile_route", "destination_rule"), drop("source_instrument_ids")), True, None),
    # R1
    ("R1 omnibus location without provider_id", "r01-funds-location-crypto-wallet.json", drop("provider_id"), False, None),
    ("R1 provider_balance without provider_id", "r01-funds-location-bank-account.json",
     both(put("provider_balance", "location_type"), drop("provider_id")), False, None),
    ("R1 crypto wallet without temperature", "r01-funds-location-crypto-wallet.json", drop("temperature"), False, None),
    ("R1 cold wallet without approvers", "r01-funds-location-crypto-wallet.json", put("cold", "temperature"), False, None),
    ("R1 bank account carrying a virtual-asset field", "r01-funds-location-bank-account.json", put("hot", "temperature"), False, None),
    ("R1 location_jurisdiction not an ISO code", "r01-funds-location-bank-account.json", put("Example", "location_jurisdiction"), False, None),
    ("R1 bank account without provider_id", "r01-funds-location-bank-account.json", drop("provider_id"), True, None),
    # R2
    ("R2 card with virtual-asset instrument_detail", "r02-payment-instrument-link-card.json",
     put({"chain": "ethereum", "address": "0xabc"}, "instrument_detail"), False, None),
    ("R2 card instrument_detail carrying a full card number", "r02-payment-instrument-link-card.json",
     put("4987123412340042", "instrument_detail", "number"), False, None),
    ("R2 card last_four with five digits", "r02-payment-instrument-link-card.json", put("12345", "instrument_detail", "last_four"), False, None),
    ("R2 holder match without verified_at", "r02-payment-instrument-link-card.json", drop("verified_at"), False, None),
    ("R2 card without funding_type", "r02-payment-instrument-link-card.json", drop("funding_type"), False, None),
    ("R2 mobile money with a raw phone number", "r02-payment-instrument-link-mobile-money.json",
     put("+254700000000", "instrument_detail", "phone_number_hash"), False, None),
    ("R2 not_checked without verification fields", "r02-payment-instrument-link-card.json",
     both(put("not_checked", "holder_match"), drop("holder_verification_method"), drop("verified_at"), drop("verified_by")), True, None),
    ("R2 carrier billing uses the mobile money module", "r02-payment-instrument-link-mobile-money.json", put("carrier_billing", "rail"), True, None),
    # R5
    ("R5 player check without subject_ref_scope", "r05-check-decision.json", drop("subject_ref_scope"), False, None),
    ("R5 sanctions check carrying exposure_categories", "r05-check-decision.json", put(["mixer"], "exposure_categories"), False, None),
    ("R5 decision outside the enumeration", "r05-check-decision.json", put("approve", "decision"), False, None),
    # R6
    ("R6 crossing purpose classes without justification", "r06-internal-movement.json", put(True, "crosses_purpose_class"), False, None),
    ("R6 source given as both location and provider", "r06-internal-movement.json", put("PSP-03", "source_provider_id"), False, None),
    ("R6 neither side a location in R1", "r06-internal-movement.json",
     both(drop("source_location_id"), drop("destination_location_id"), put("PSP-03", "source_provider_id"), put("EXCH-01", "destination_provider_id")), False, None),
    ("R6 provider on one side only", "r06-internal-movement.json", both(drop("source_location_id"), put("PSP-03", "source_provider_id")), True, None),
    # R7
    ("R7 coverage statement carrying a location field", COV, put("100.00", "opening_balance_ledger"), False, None),
    ("R7 location statement without unexplained_delta", "r07-location-statement.json", drop("unexplained_delta"), False, None),
    ("R7 funds_held keyed by an unknown mechanism", COV, put("10.00", "funds_held", "cash_in_drawer"), False, None),
    ("R7 coverage statement without shortfall", COV, drop("shortfall"), False, None),
    # R8
    ("R8 resolved without resolved_at", "r08-exception.json", drop("resolved_at"), False, None),
    ("R8 category outside the closed list", "r08-exception.json", put("other", "category"), False, None),
    ("R8 open exception carrying resolved_at", "r08-exception.json", put("open", "status"), False, None),
    ("R8 amount without currency_or_asset", "r08-exception.json", drop("currency_or_asset"), False, None),
    ("R8 amount without amount_reporting_ccy", "r08-exception.json", drop("amount_reporting_ccy"), False, None),
    ("R8 open exception without resolution", "r08-exception.json",
     both(put("open", "status"), drop("resolved_at"), drop("resolution_code"), drop("resolution_note")), True, None),
    # R9
    ("R9 closed incident without notified_at", "r09-incident.json", drop("notified_at"), False, None),
    ("R9 pending notification carrying notified_at", "r09-incident.json", put("pending_notification", "status"), False, None),
    ("R9 pending notification without notified_at or channel", "r09-incident.json",
     both(put("pending_notification", "status"), drop("notified_at"), drop("channel")), True, None),
    # R10 to R12
    ("R10 virtual-asset provider without travel_rule_capable", "r10-provider-register.json", drop("travel_rule_capable"), False, None),
    ("R10 provider_role outside the enumeration", "r10-provider-register.json", put("exchange", "provider_role"), False, None),
    ("R11 without covers_location_ids", "r11-provider-attestation.json", drop("covers_location_ids"), False, None),
    ("R12 report_type outside the enumeration", "r12-report-reference.json", put("sar_content", "report_type"), False, None),
    ("R12 filed_at not_recorded (visible gap)", "r12-report-reference.json", put("not_recorded", "filed_at"), True, None),
    ("R12 profile_rule_ref without profile version", "r12-report-reference.json", put("XJ#rep-cash-threshold", "profile_rule_ref"), False, None),
    # Manifest
    ("manifest sha256 in upper case", "manifest-periodic-package.json", put("A" * 64, "files", 0, "sha256"), False, None),
    ("manifest for another version of the Standard", "manifest-periodic-package.json", put("2.0", "standard_version"), False, None),
    ("manifest with no files", "manifest-periodic-package.json", put([], "files"), False, None),
    ("manifest with record type R13", "manifest-periodic-package.json", put("R13", "files", 0, "record_type"), False, None),
    ("manifest supersedes without reason", "manifest-correction.json", drop("supersedes", "reason"), False, None),
    ("manifest with R3 and R4 files but no reporting_currency", "manifest-periodic-package.json", drop("reporting_currency"), False, None),
    ("manifest file format csv on a .jsonl file", "manifest-periodic-package.json", put("csv", "files", 0, "format"), False, None),
    ("manifest without R3 or R4 files and no reporting_currency", "manifest-periodic-package.json",
     both(drop("reporting_currency"),
          lambda d: d.__setitem__("files", [x for x in d["files"] if x["record_type"] not in ("R3", "R4")])), True, None),
    ("manifest CSV file at Level 1", "manifest-periodic-package.json",
     both(put("csv", "files", 0, "format"), put("R1_funds_locations.csv", "files", 0, "file")), True, None),
    # Profile
    ("profile with status draft", "profile-xj-example-jurisdiction.json", put("draft", "status"), False, None),
    ("profile confirmed without confirmed_by", "profile-xj-example-jurisdiction.json", put("confirmed", "status"), False, None),
    ("profile without a retention block", "profile-xj-example-jurisdiction.json", drop("parameters", "retention"), False, None),
    ("profile threshold in both currency and indexed units", "profile-xj-example-jurisdiction.json",
     put("XBU", "parameters", "check_thresholds", "thresholds", 0, "threshold", "indexed_unit"), False, None),
    ("profile rolling window without length", "profile-xj-example-jurisdiction.json",
     drop("parameters", "check_thresholds", "thresholds", 0, "aggregation", "length"), False, None),
    ("profile deadline with both duration and day of month", "profile-xj-example-jurisdiction.json",
     put(5, "parameters", "report_triggers", "triggers", 0, "deadline", "day_of_following_month"), False, None),
    ("profile parameter block without reading", "profile-xj-example-jurisdiction.json", drop("parameters", "data_vault", "reading"), False, None),
    ("profile with an undefined parameter block", "profile-xj-example-jurisdiction.json", put({"reading": "stated"}, "parameters", "scoring"), False, None),
    ("profile conditional rail without conditions", "profile-xj-example-jurisdiction.json",
     drop("parameters", "permitted_rails", "rails", 0, "conditions"), False, None),
    ("profile threshold-based report trigger without aggregation", "profile-xj-example-jurisdiction.json",
     drop("parameters", "report_triggers", "triggers", 0, "aggregation"), False, None),
    ("profile periodic submission mode without cadence", "profile-xj-example-jurisdiction.json",
     drop("parameters", "submission", "modes", 0, "cadence"), False, None),
    ("inheriting profile without inherits_from","profile-xj-n-inheriting-example.json", drop("inherits_from"), False, None),
    ("profile confirmed with confirmed_by and confirmed_at", "profile-xj-example-jurisdiction.json",
     both(put("confirmed", "status"), put("Example Gambling Authority (fictional)", "confirmed_by"), put("2026-12-01", "confirmed_at")), True, None),
]

for description, example, mutate, expected_valid, override in CASES:
    if example not in examples:
        fail(f"{description}: example {example} not found")
        continue
    instance = copy.deepcopy(examples[example])
    mutate(instance)
    sp = override or schema_path_for(example)
    errs = errors_of(instance, sp)
    valid = not errs
    if valid == expected_valid:
        ok(f"{description}: {'passes' if valid else 'fails'} as expected")
    else:
        fail(f"{description}: expected {'valid' if expected_valid else 'invalid'}, got {'valid' if valid else 'invalid'}")
        for e in errs[:5]:
            print(f"          {e}")

# ---------------------------------------------------------------------------------------------
print()
if failures:
    print(f"{len(failures)} check(s) failed.")
    sys.exit(1)
print(f"All checks passed: {len(schemas)} schemas, {len(examples)} examples, {len(CASES)} broken or varied copies.")
