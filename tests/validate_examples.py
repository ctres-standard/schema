#!/usr/bin/env python3
"""Validate the CTRES v1.1 JSON Schema package.

Checks, in order:

1. Every file under schema/ is a valid JSON Schema (draft 2020-12) document whose $id
   lies under https://ctres.org/schema/1.1/ and matches its path, and that the package
   holds the expected number of schemas.
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
BASE_ID = "https://ctres.org/schema/1.1/"
# common, rail modules, payment, manifest, profile, one schema per record type R1 to R15, and the stream
# event envelope and checkpoint. The reference transport, stream/openapi.yaml, is not a schema.
EXPECTED_SCHEMA_COUNT = 22

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
if len(schemas) != EXPECTED_SCHEMA_COUNT:
    fail(f"expected {EXPECTED_SCHEMA_COUNT} schemas, found {len(schemas)}")
else:
    ok(f"{len(schemas)} schemas")

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
    if example_name.startswith("stream-event"):
        return SCHEMA_DIR / "stream" / "event.schema.json"
    if example_name.startswith("stream-checkpoint"):
        return SCHEMA_DIR / "stream" / "checkpoint.schema.json"
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

# Every record type, the manifest, the profile, the stream event and the checkpoint have at least one example.
covered = {schema_path_for(n).name for n in examples}
for sp in schema_files:
    if sp.parent.name in ("records", "stream") or sp.name in ("manifest.schema.json", "profile.schema.json"):
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
R13O = "r13-gaming-revenue-statement-online.json"
R13C = "r13-gaming-revenue-statement-correction.json"
R13V = "r13-gaming-revenue-statement-venue.json"
R14S = "r14-venue-count-slot-machine.json"
R14T = "r14-venue-count-table.json"
R14V = "r14-venue-count-venue-total.json"
M11 = "manifest-periodic-package-1.1.json"
XJ = "profile-xj-example-jurisdiction.json"
RL = ("parameters", "revenue_and_levy")
SUB = ("parameters", "submission")
R15O, R15S, R15V = "r15-bet-event-open.json", "r15-bet-event-settled.json", "r15-bet-event-void.json"
EV3, EV15, EVCP, CP = "stream-event-r3-create.json", "stream-event-r15-update.json", "stream-event-checkpoint.json", "stream-checkpoint.json"
R04 = SCHEMA_DIR / "records" / "r04_withdrawal.schema.json"
R15 = SCHEMA_DIR / "records" / "r15_bet_event.schema.json"

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
    ("manifest 1.0 package listing an R13 file", "manifest-periodic-package.json", put("R13", "files", 0, "record_type"), False, None),
    ("manifest 1.0 package listing an R15 file", "manifest-periodic-package.json", put("R15", "files", 0, "record_type"), False, None),
    ("manifest with record type R16", "manifest-periodic-package.json", put("R16", "files", 0, "record_type"), False, None),
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
    # R13
    ("R13 correction without corrects_statement_id", R13C, drop("corrects_statement_id"), False, None),
    ("R13 correction without correction_reason", R13C, drop("correction_reason"), False, None),
    ("R13 period statement carrying corrects_statement_id", R13O, put("GRS-2026-12-X", "corrects_statement_id"), False, None),
    ("R13 statement_kind outside the enumeration", R13O, put("restatement", "statement_kind"), False, None),
    ("R13 ggr_declared as a JSON number", R13O, put(265550.0, "ggr_declared"), False, None),
    ("R13 stakes_bonus without bonus_measurement", R13O, drop("bonus_measurement"), False, None),
    ("R13 open_liability_start without open_liability_end", R13O, drop("open_liability_end"), False, None),
    ("R13 jackpot_contributions without jackpot_payouts", R13O, drop("jackpot_payouts"), False, None),
    ("R13 levy_amount_declared without levy_base_declared", R13O, drop("levy_base_declared"), False, None),
    ("R13 fx_rate without fx_source and fx_at", R13O, put("1.00", "fx_rate"), False, None),
    ("R13 channel outside the enumeration", R13O, put("mobile", "channel"), False, None),
    ("R13 authority_figure_ref without figure", R13O, drop("authority_figure_ref", "figure"), False, None),
    ("R13 with an undefined field", R13O, put("1000.00", "ngr_declared"), False, None),
    ("R13 fx_rate with fx_source and fx_at", R13O,
     both(put("XJD", "currency"), put("0.85", "fx_rate"), put("Example Central Bank monthly rate (fictional)", "fx_source"),
          put("2027-01-31T23:59:59+01:00", "fx_at")), True, None),
    ("R13 negative ggr_declared (negative period)", R13O, put("-12040.00", "ggr_declared"), True, None),
    ("R13 evidence_ref not_recorded (visible gap)", R13O, put("not_recorded", "evidence_ref"), True, None),
    ("R13 without bonus fields or bonus_measurement", R13C,
     both(drop("stakes_bonus"), drop("winnings_bonus"), drop("bonus_granted"), drop("bonus_expired"), drop("bonus_measurement")), True, None),
    ("R13 stakes_bonus without bonus_granted and bonus_expired", R13O, both(drop("bonus_granted"), drop("bonus_expired")), False, None),
    ("R13 winnings_bonus without bonus_granted and bonus_expired", R13C,
     both(drop("stakes_bonus"), drop("bonus_granted"), drop("bonus_expired")), False, None),
    ("R13 stakes_basis outside the enumeration", R13O, put("accrued", "stakes_basis"), False, None),
    ("R13 venue_id as a JSON number", R13V, put(7, "venue_id"), False, None),
    ("R13 player_location not an ISO code", R13O, put("Example", "player_location"), False, None),
    ("R13 stakes_basis accrual_at_result", R13O, put("accrual_at_result", "stakes_basis"), True, None),
    ("R13 player_location with a subdivision", R13O, put("XJ-N", "player_location"), True, None),
    ("R13 venue line without venue_id (condition depends on the licence and the profile)", R13V, drop("venue_id"), True, None),
    ("R13 without authority_figure_ref (condition depends on the profile)", R13O, drop("authority_figure_ref"), True, None),
    # R14
    ("R14 slot row without meters", R14S, both(drop("meters_start"), drop("meters_end")), False, None),
    ("R14 slot row without meters_end", R14S, drop("meters_end"), False, None),
    ("R14 slot meters without coin_in", R14S, drop("meters_start", "coin_in"), False, None),
    ("R14 slot meters with an undefined meter", R14S, put("1.00", "meters_end", "handle"), False, None),
    ("R14 slot meters with cashless transfers and progressive payouts", R14S,
     both(put("1250.00", "meters_end", "wat_in"), put("980.00", "meters_end", "wat_out"),
          put("500.00", "meters_end", "progressive_payouts_attendant_paid")), True, None),
    ("R14 slot row carrying hard_count", R14S, put("100.00", "hard_count"), False, None),
    ("R14 table row without drop_cash", R14T, drop("drop_cash"), False, None),
    ("R14 table row without fills", R14T, drop("fills"), False, None),
    ("R14 table row carrying meters", R14T, put({"coin_in": "1.00", "coin_out": "0.00"}, "meters_start"), False, None),
    ("R14 venue_total without counts", R14V, both(drop("hard_count"), drop("soft_count"), drop("count_variance")), False, None),
    ("R14 venue_total without count_variance", R14V, drop("count_variance"), False, None),
    ("R14 without gaming_day or period", R14S, drop("gaming_day"), False, None),
    ("R14 with both gaming_day and period", R14S,
     both(put("2027-01-14T00:00:00+01:00", "period_start"), put("2027-01-14T23:59:59+01:00", "period_end")), False, None),
    ("R14 win_formula outside the enumeration", R14T, put("house_formula", "win_formula"), False, None),
    ("R14 win_declared as a JSON number", R14T, put(7570.0, "win_declared"), False, None),
    ("R14 meter_source outside the enumeration", R14S, put("unknown", "meter_source"), False, None),
    ("R14 counter row without closing_inventory", R14T, both(put("counter", "unit_type"), drop("closing_inventory")), False, None),
    ("R14 period count in place of gaming_day", R14S,
     both(drop("gaming_day"), put("2027-01-01T00:00:00+01:00", "period_start"), put("2027-01-31T23:59:59+01:00", "period_end")), True, None),
    ("R14 meter_source not_recorded (visible gap)", R14S, put("not_recorded", "meter_source"), True, None),
    ("R14 table win negative", R14T, put("-1430.00", "win_declared"), True, None),
    ("R14 counter row with inventories only", R14T,
     both(put("counter", "unit_type"), put("C-01", "unit_id"), drop("fills"), drop("credits"), drop("drop_cash"), drop("drop_markers"),
          drop("coupons_face_value"), drop("tips_excluded"), put("profile", "win_formula")), True, None),
    ("R14 slot row with meter_source not_recorded and no meters", R14S,
     both(put("not_recorded", "meter_source"), drop("meters_start"), drop("meters_end"), put("slot_drop_formula", "win_formula"),
          put("740.00", "drop_cash"), put("0.00", "fills")), True, None),
    ("R14 slot row by the drop formula without drop_cash and fills", R14S, put("slot_drop_formula", "win_formula"), False, None),
    ("R14 slot row by the drop formula with drop and fills", R14S,
     both(put("slot_drop_formula", "win_formula"), put("740.00", "drop_cash"), put("0.00", "fills")), True, None),
    ("R14 slot row by the table formula", R14S, put("table_drop_formula", "win_formula"), False, None),
    ("R14 table row by a slot formula", R14T, put("slot_meter_formula", "win_formula"), False, None),
    ("R14 slot row by the profile's formula", R14S, put("profile", "win_formula"), True, None),
    ("R14 venue_total row by the table formula (formula free on venue_total and counter rows)", R14V, put("table_drop_formula", "win_formula"), True, None),
    # R1 venue_id and R12 levy_return
    ("R1 cash float with venue_id", "r01-funds-location-bank-account.json",
     both(put("cash_float", "location_type"), put("V-NORTH-01", "venue_id")), True, None),
    ("R1 venue_id as a JSON number", "r01-funds-location-bank-account.json", put(7, "venue_id"), False, None),
    ("R12 report_type levy_return", "r12-report-reference.json", put("levy_return", "report_type"), True, None),
    # Manifest 1.1
    ("manifest with R13 but standard_version 1.0", M11, put("1.0", "standard_version"), False, None),
    ("manifest with R14 but standard_version 1.0", M11,
     both(put("1.0", "standard_version"),
          lambda d: d.__setitem__("files", [x for x in d["files"] if x["record_type"] != "R13"])), False, None),
    ("manifest 1.1 package without R13 or R14 files", M11,
     lambda d: d.__setitem__("files", [x for x in d["files"] if x["record_type"] not in ("R13", "R14")]), True, None),
    ("manifest without R13 or R14 declaring standard_version 1.1", "manifest-periodic-package.json", put("1.1", "standard_version"), True, None),
    ("manifest report_reference_counts with levy_return", "manifest-periodic-package.json",
     lambda d: d["report_reference_counts"].append(
         {"report_type": "levy_return", "total": 1, "filed_by_deadline": 1, "filed_after_deadline": 0, "not_filed": 0}), True, None),
    # Manifest: conformance levels (§10)
    ("manifest declaring level_4", M11, put("level_4", "conformance_level_declared"), True, None),
    ("manifest declaring level_1", M11, put("level_1", "conformance_level_declared"), True, None),
    ("manifest declaring level_5", M11, put("level_5", "conformance_level_declared"), False, None),
    ("manifest declaring a level by name rather than code", M11, put("Level 1", "conformance_level_declared"), False, None),
    ("manifest without a declared level", M11, drop("conformance_level_declared"), True, None),
    # Profile: Revenue and levy (five parameters and notes, §5)
    ("profile revenue_and_levy without levy_formula", XJ, drop(*RL, "levy_formula"), False, None),
    ("profile revenue_and_levy without recognition", XJ, drop(*RL, "recognition"), False, None),
    ("profile revenue_and_levy without period_and_filing", XJ, drop(*RL, "period_and_filing"), False, None),
    ("profile revenue_and_levy without reading", XJ, drop(*RL, "reading"), False, None),
    ("profile levy formula term with an unknown quantity", XJ, put("net_profit", *RL, "levy_formula", 0, "terms", 0, "quantity"), False, None),
    ("profile levy formula term with a sign other than + or -", XJ, put("minus", *RL, "levy_formula", 0, "terms", 2, "sign"), False, None),
    ("profile levy formula term without a sign", XJ, drop(*RL, "levy_formula", 0, "terms", 2, "sign"), False, None),
    ("profile levy base_type outside the enumeration", XJ, put("ngr", *RL, "levy_formula", 0, "base_type"), False, None),
    ("profile levy formula without applies_to", XJ, drop(*RL, "levy_formula", 0, "applies_to"), False, None),
    ("profile levy formula with rate and bands together", XJ, put([{"up_to": None, "rate": "0.10"}], *RL, "levy_formula", 0, "bands"), False, None),
    ("profile levy formula with neither rate, bands nor fixed_amount", XJ, drop(*RL, "levy_formula", 0, "rate"), False, None),
    ("profile ggr formula without terms", XJ, drop(*RL, "levy_formula", 0, "terms"), False, None),
    ("profile fixed_per_unit formula without fixed_amount", XJ,
     both(drop(*RL, "levy_formula", 2, "fixed_amount"), put("0.10", *RL, "levy_formula", 2, "rate")), False, None),
    ("profile fixed_amount per outside the enumeration", XJ, put("player", *RL, "levy_formula", 2, "fixed_amount", "per"), False, None),
    ("profile band without up_to", XJ,
     both(drop(*RL, "levy_formula", 0, "rate"), put([{"rate": "0.20"}], *RL, "levy_formula", 0, "bands")), False, None),
    ("profile term cap with share but no share_of", XJ, put({"share": "0.20"}, *RL, "levy_formula", 0, "terms", 5, "cap"), False, None),
    ("profile term cap with both a share and an amount", XJ,
     put({"share_of": "stakes_cash", "share": "0.20", "amount": "1000.00", "currency": "EUR"}, *RL, "levy_formula", 0, "terms", 5, "cap"), False, None),
    ("profile term cap share_of outside the R13 quantities", XJ, put("ggr", *RL, "levy_formula", 0, "terms", 5, "cap", "share_of"), False, None),
    ("profile venue win formula that does not fit the unit", XJ,
     put("slot_meter_formula", *RL, "levy_formula", 2, "venue_win_formulas", "table"), False, None),
    ("profile recognition stakes_basis outside the enumeration", XJ, put("accrued", *RL, "recognition", "stakes_basis"), False, None),
    ("profile recognition without winnings_basis", XJ, drop(*RL, "recognition", "winnings_basis"), False, None),
    ("profile period outside the enumeration", XJ, put("monthly", *RL, "period_and_filing", "period"), False, None),
    ("profile collector outside the enumeration", XJ, put("ministry", *RL, "period_and_filing", "collector"), False, None),
    ("profile figure_of_record outside the enumeration", XJ, put("auditor", *RL, "period_and_filing", "figure_of_record"), False, None),
    ("profile negative period rule outside the enumeration", XJ, put("offset", *RL, "negative_periods", "rule"), False, None),
    ("profile netting scope outside the enumeration", XJ, put("premises", *RL, "negative_periods", "netting_scope"), False, None),
    ("profile aggregation axis outside the enumeration", XJ, put(["product_line", "premises"], *RL, "aggregation", "axes"), False, None),
    ("profile aggregation taxonomy without ref", XJ, drop(*RL, "aggregation", "taxonomy", "ref"), False, None),
    ("profile notes with an undefined key", XJ, put("x", *RL, "notes", "rounding"), False, None),
    ("profile revenue_and_levy with an undefined parameter", XJ, put({"basis": "stated"}, *RL, "rounding"), False, None),
    ("profile revenue_and_levy with a former switch", XJ, put({"basis": "placed"}, *RL, "stake_recognition"), False, None),
    ("profile with revenue_and_levy declaring ctres_version 1.0", XJ, put("1.0", "ctres_version"), False, None),
    ("profile minimum_conformance_level level_5", XJ, put("level_5", "parameters", "submission", "minimum_conformance_level"), False, None),
    ("profile revenue_and_levy as published", XJ, lambda d: None, True, None),
    ("profile term cap as an amount", XJ, put({"amount": "100000.00", "currency": "EUR"}, *RL, "levy_formula", 0, "terms", 5, "cap"), True, None),
    ("profile levy by bands with an open top band", XJ,
     both(drop(*RL, "levy_formula", 0, "rate"),
          put([{"up_to": "1000000.00", "rate": "0.15"}, {"up_to": None, "rate": "0.20"}], *RL, "levy_formula", 0, "bands")), True, None),
    ("profile fee_band formula", XJ,
     put({"applies_to": ["*"], "base_type": "fee_band",
          "terms": [{"quantity": "stakes_cash", "sign": "+"}, {"quantity": "winnings_cash", "sign": "-"}],
          "bands": [{"up_to": "500000.00", "rate": "0.05"}, {"up_to": None, "rate": "0.01"}]}, *RL, "levy_formula", 1), True, None),
    ("profile revenue_and_levy minimal block", XJ,
     put({"reading": "stated",
          "levy_formula": [{"applies_to": ["*"], "base_type": "turnover", "terms": [{"quantity": "stakes_cash", "sign": "+"}], "rate": "0.053"}],
          "recognition": {"stakes_basis": "placed", "winnings_basis": "paid"},
          "period_and_filing": {"period": "month"}}, *RL), True, None),
    ("profile minimum_conformance_level level_1", XJ, put("level_1", "parameters", "submission", "minimum_conformance_level"), True, None),
    ("profile without minimum_conformance_level", XJ, drop("parameters", "submission", "minimum_conformance_level"), True, None),
    ("profile without revenue_and_levy declaring ctres_version 1.0", XJ,
     both(drop(*RL), put("1.0", "ctres_version")), True, None),
    # R15 Bet Event (Wagering module, §4.15)
    ("R15 open bet as published", R15O, lambda d: None, True, None),
    ("R15 without bet_id", R15O, drop("bet_id"), False, None),
    ("R15 without player_ref_scope", R15O, drop("player_ref_scope"), False, None),
    ("R15 stake as a JSON number", R15O, put(25.0, "stake"), False, None),
    ("R15 negative stake", R15O, put("-25.00", "stake"), False, None),
    ("R15 channel outside the enumeration", R15O, put("mobile", "channel"), False, None),
    ("R15 status outside the enumeration", R15O, put("pending", "status"), False, None),
    ("R15 currency that is not an ISO 4217 code", R15O, put("USDT-ERC20", "currency"), False, None),
    ("R15 open bet with winnings 10.00", R15O, put("10.00", "winnings"), False, None),
    ("R15 open bet with winnings 0.00", R15O, put("0.00", "winnings"), True, None),
    ("R15 open bet carrying settled_at", R15O, put("2027-01-14T21:03:55+01:00", "settled_at"), False, None),
    ("R15 open bet carrying void_reason", R15O, put("Event cancelled", "void_reason"), False, None),
    ("R15 settled bet without settled_at", R15S, drop("settled_at"), False, None),
    ("R15 settled bet carrying void_reason", R15S, put("Event cancelled", "void_reason"), False, None),
    ("R15 void bet without void_reason", R15V, drop("void_reason"), False, None),
    ("R15 void bet without settled_at", R15V, drop("settled_at"), False, None),
    ("R15 void bet carrying winnings 0.00", R15V, put("0.00", "winnings"), True, None),
    ("R15 cashed-out bet with settled_at and winnings", R15O,
     both(put("cashed_out", "status"), put("2027-01-14T20:10:00+01:00", "settled_at"), put("31.20", "winnings")), True, None),
    ("R15 cashed-out bet without settled_at", R15O, both(put("cashed_out", "status"), put("31.20", "winnings")), False, None),
    ("R15 odds that are not a decimal string", R15O, put("12/5", "odds"), False, None),
    ("R15 negative odds (American format)", R15O, put("-110", "odds"), True, None),
    ("R15 jurisdiction_category not in snake_case", R15O, put("Betting", "jurisdiction_category"), False, None),
    ("R15 ledger_entry_refs with a repeated entry", R15S, put(["LE-1", "LE-1"], "ledger_entry_refs"), False, None),
    ("R15 with an undefined field", R15O, put("P-20931", "player_name"), False, None),
    ("R15 venue bet without venue_id (condition depends on the licence and the profile)", R15V, drop("venue_id"), True, None),
    ("R15 with authority_reference and rake_and_fees", R15S,
     both(put("XJ-HUB-2027-01-14-00044120", "authority_reference"), put("0.05", "rake_and_fees")), True, None),
    ("R15 settled bet with the core fields only and settled_at", R15S,
     both(drop("stake_bonus"), drop("winnings"), drop("winnings_bonus"), drop("jurisdiction_category"), drop("game_ref"),
          drop("jackpot_contribution"), drop("ledger_entry_refs"), drop("evidence_ref")), True, None),
    ("R15 validated as R4", R15O, lambda d: None, False, R04),
    ("R3 deposit validated as R15", CARD, lambda d: None, False, R15),
    # Stream event envelope (§8.4)
    ("stream event with a well-formed envelope (R3 create)", EV3, lambda d: None, True, None),
    ("stream event with a well-formed envelope (R15 update)", EV15, lambda d: None, True, None),
    ("stream event with a well-formed envelope (checkpoint)", EVCP, lambda d: None, True, None),
    ("stream event with sequence 1", EV3, put(1, "sequence"), True, None),
    ("stream event with sequence 0", EV3, put(0, "sequence"), False, None),
    ("stream event with sequence as a string", EV3, put("10482", "sequence"), False, None),
    ("stream event without stream_id", EV3, drop("stream_id"), False, None),
    ("stream event without emitted_at", EV3, drop("emitted_at"), False, None),
    ("stream event emitted_at without offset", EV3, put("2027-01-14T18:40:07", "emitted_at"), False, None),
    ("stream event without licence_number", EV3, drop("licence_number"), False, None),
    ("stream event standard_version 1.0", EV3, put("1.0", "standard_version"), False, None),
    ("stream event without profile_id", EV3, drop("profile_id"), True, None),
    ("stream event profile_id in lower case", EV3, put("xj-2026-1", "profile_id"), False, None),
    ("stream event with an unknown record_type", EV3, put("R16", "record_type"), False, None),
    ("stream event record_type in lower case", EV3, put("r3", "record_type"), False, None),
    ("stream event op not in the enumeration", EV3, put("delete", "op"), False, None),
    ("stream event with an undefined envelope field", EV3, put("abc", "signature"), False, None),
    ("stream event record_type R3 with an invalid R3 record", EV3, drop("record", "tx_id"), False, None),
    ("stream event record_type R3 with a record that is not an object", EV3, put("D-2027-01-14-000731", "record"), False, None),
    ("stream event record_type R3 whose record carries an undefined field", EV3, put("blue", "record", "colour"), False, None),
    ("stream event R3 record validated as R4 (record_type R4)", EV3, put("R4", "record_type"), False, None),
    ("stream event R15 update with an open bet carrying winnings", EV15, put("open", "record", "status"), False, None),
    ("stream event op void with only the identifier", EV3, both(put("void", "op"), put({"tx_id": "D-2027-01-14-000731"}, "record"),
                                                               put("Booked twice; the other booking stands", "reason")), True, None),
    ("stream event op void with the whole record", EV3, both(put("void", "op"), put("Booked twice", "reason")), True, None),
    ("stream event op void with an empty record", EV3, both(put("void", "op"), put({}, "record")), False, None),
    ("stream event op void with reason longer than free text permits", EV3, both(put("void", "op"), put("x" * 4001, "reason")), False, None),
    ("stream event checkpoint with op update", EVCP, put("update", "op"), False, None),
    ("stream event checkpoint with op void", EVCP, both(put("void", "op"), put("withdrawn", "reason")), False, None),
    ("stream event checkpoint without chain_hash", EVCP, drop("record", "chain_hash"), False, None),
    ("stream event checkpoint carrying a record field", EVCP, put("x", "record", "tx_id"), False, None),
    # Stream checkpoint (§8.4)
    ("stream checkpoint as published", CP, lambda d: None, True, None),
    ("stream checkpoint with non-hex chain_hash", CP, put("g" * 64, "chain_hash"), False, None),
    ("stream checkpoint with chain_hash in upper case", CP, put("A" * 64, "chain_hash"), False, None),
    ("stream checkpoint with chain_hash of 63 characters", CP, put("a" * 63, "chain_hash"), False, None),
    ("stream checkpoint without event_count", CP, drop("event_count"), False, None),
    ("stream checkpoint with first_sequence 0", CP, put(0, "first_sequence"), False, None),
    ("stream checkpoint with negative event_count", CP, put(-1, "event_count"), False, None),
    ("stream checkpoint with event_count as a string", CP, put("719", "event_count"), False, None),
    ("stream checkpoint with previous_checkpoint_hash not hex", CP, put("none", "previous_checkpoint_hash"), False, None),
    ("stream checkpoint with a signature", CP, put("MEUCIQ...", "signature"), True, None),
    ("stream checkpoint with an empty signature", CP, put("", "signature"), False, None),
    ("stream checkpoint without previous_checkpoint_hash", CP, drop("previous_checkpoint_hash"), True, None),
    ("stream checkpoint for a period without events", CP,
     both(put(10001, "first_sequence"), put(10000, "last_sequence"), put(0, "event_count")), True, None),
    ("stream checkpoint with an undefined field", CP, put("R3", "record_type"), False, None),
    # Manifest: R15 files and stream_checkpoints
    ("manifest with R15 but standard_version 1.0", M11,
     both(put("1.0", "standard_version"),
          lambda d: d.__setitem__("files", [dict(x, record_type="R15", file="R15_bet_events.jsonl") for x in d["files"][:1]])), False, None),
    ("manifest 1.1 package listing an R15 file", M11,
     lambda d: d["files"].append({"file": "R15_bet_events.jsonl", "record_type": "R15", "record_count": 2410,
                                  "sha256": "a" * 64}), True, None),
    ("manifest stream_checkpoints as published", M11, lambda d: None, True, None),
    ("manifest without stream_checkpoints", M11, drop("stream_checkpoints"), True, None),
    ("manifest with empty stream_checkpoints", M11, put([], "stream_checkpoints"), False, None),
    ("manifest stream_checkpoints entry without chain_hash", M11, drop("stream_checkpoints", 0, "chain_hash"), False, None),
    ("manifest stream_checkpoints entry with non-hex chain_hash", M11, put("z" * 64, "stream_checkpoints", 0, "chain_hash"), False, None),
    ("manifest stream_checkpoints entry that is an event envelope", M11,
     lambda d: d.__setitem__("stream_checkpoints", [examples[EVCP]]), False, None),
    ("manifest stream_checkpoints with submission_mode continuous", M11, put("continuous", "submission_mode"), True, None),
    # R13 interim statements (§4.13; §8.4)
    ("R13 interim statement", R13O, put("interim", "statement_kind"), True, None),
    ("R13 interim statement carrying corrects_statement_id", R13O,
     both(put("interim", "statement_kind"), put("GRS-2026-12-X", "corrects_statement_id")), False, None),
    # Profile: submission stream parameters (§8.4; §5)
    ("profile submission stream parameters as published", XJ, lambda d: None, True, None),
    ("profile submission.mode stream", XJ, put("stream", *SUB, "mode"), False, None),
    ("profile submission.mode periodic", XJ, put("periodic", *SUB, "mode"), True, None),
    ("profile latency 60s (not ISO 8601)", XJ, put("60s", *SUB, "latency", "R3"), False, None),
    ("profile latency as a JSON number", XJ, put(60, *SUB, "latency", "R3"), False, None),
    ("profile latency for an unknown record type", XJ, put("PT60S", *SUB, "latency", "R16"), False, None),
    ("profile latency for a checkpoint", XJ, put("PT60S", *SUB, "latency", "checkpoint"), False, None),
    ("profile empty latency", XJ, put({}, *SUB, "latency"), False, None),
    ("profile latency PT0S and P1D", XJ, put({"R9": "PT0S", "R7": "P1D"}, *SUB, "latency"), True, None),
    ("profile checkpoint outside the enumeration", XJ, put("daily", *SUB, "checkpoint"), False, None),
    ("profile checkpoint hour", XJ, put("hour", *SUB, "checkpoint"), True, None),
    ("profile bet_level as a string", XJ, put("yes", *SUB, "bet_level"), False, None),
    ("profile bet_level false", XJ, put(False, *SUB, "bet_level"), True, None),
    ("profile transport outside the enumeration", XJ, put("sftp", *SUB, "transport"), False, None),
    ("profile transport pull", XJ, put("pull", *SUB, "transport"), True, None),
    ("profile continuous mode listing R15", XJ, put(["R15"], *SUB, "modes", 1, "record_types"), True, None),
    ("profile mode listing an unknown record type", XJ, put(["R16"], *SUB, "modes", 1, "record_types"), False, None),
    ("profile without the stream parameters", XJ,
     both(drop(*SUB, "mode"), drop(*SUB, "latency"), drop(*SUB, "checkpoint"), drop(*SUB, "bet_level"), drop(*SUB, "transport")), True, None),
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
