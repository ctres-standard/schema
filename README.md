# CTRES JSON Schema

This repository holds the machine-readable schema of the **Common Transaction Reporting and Evidence Standard (CTRES) v1.0**, universal edition, dated 2 October 2026. It is the field catalogue referred to in Annex A of the Standard.

The schema is written in JSON Schema draft 2020-12. Section references (§) in the schema and in this document are to the text of the Standard, published at <https://ctres.org> and in the repository [ctres-standard/spec](https://github.com/ctres-standard/spec). Where the schema and the text differ, the text prevails and the difference is a defect in the schema.

Status: draft for consultation. The schema carries no regulatory force and is not endorsed by any authority.

## Contents

| Path | Content |
|---|---|
| `schema/common.schema.json` | Shared types: decimal strings, timestamps with an explicit offset, dates, durations, ISO 4217 codes and virtual-asset identifiers, identifiers, the player key pair, the `not_recorded` marker (§3, §8.2), and enumerations used by more than one record. |
| `schema/rail_modules.schema.json` | Rail-module fields (§6): the shape of `instrument_detail` in R2 for each rail, and the fields each rail adds to R1, R3, R4 and R5. |
| `schema/payment.schema.json` | The fields R3 Deposit and R4 Withdrawal share (§4.3, §4.4). |
| `schema/records/r01_funds_location.schema.json` … `r12_report_reference.schema.json` | One schema per record type, R1 to R12 (§4). `r03_deposit` and `r04_withdrawal` apply `payment.schema.json` and fix the direction. |
| `schema/manifest.schema.json` | `manifest.json`, carried by every package (§8.2). |
| `schema/profile.schema.json` | The structure of a jurisdiction profile (§5). It defines the parameters a profile may set; it contains no profile. |
| `examples/` | Valid examples of every record type, the manifest and a profile. See [Examples](#examples). |
| `tests/validate_examples.py` | Checks the schemas and validates every example; also checks that deliberately broken copies fail. |

Every schema has an `$id` under `https://ctres.org/schema/1.0/`. References between files are relative, so the schemas can be used from a local copy without network access.

## Versioning

The schema follows the versioning rule of §13: major versions change the record model; minor versions add fields, rails or profile parameters; patches correct text.

* The package version is `MAJOR.MINOR.PATCH`. `MAJOR.MINOR` is the version of the Standard the schema implements; this release is **1.0.0**, for CTRES v1.0.
* The `$id` path carries `MAJOR.MINOR` (`/schema/1.0/`). A patch release keeps the same `$id`s and does not change which records are valid, except to correct a schema that contradicts the text.
* `manifest.json` names the version of the Standard in `standard_version` and the profile in `profile_id` and `profile_version`, so that a package is always validated against the schema version it was produced for.
* Jurisdiction profiles, mapping files and the conformance suite are versioned separately from the schema (§13).

## Scope

The schema expresses the **structural** class of validation in §11: required fields present, types and enumerations valid, conditional fields present where the record itself shows the condition.

The **referential** class (every payment references an instrument in R2 and a provider in R10, every check reference resolves, manifest hashes match the files) spans several records and files and cannot be expressed in JSON Schema. It is implemented by the reference validator in [ctres-standard/validator-lite](https://github.com/ctres-standard/validator-lite).

Profile conformance and completeness (§11) are outside this repository. They are maintained separately as a versioned conformance suite, as §11 describes.

## Validating a record

Packages are JSON Lines: one record per line, one record type per file (§8.2). Validate each line against the schema for its record type. With Python and the `jsonschema` package:

```python
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMA = Path("schema")  # a local copy of this repository's schema/ directory

# Register every schema under its $id so that relative $refs resolve locally.
docs = [json.loads(p.read_text(encoding="utf-8")) for p in SCHEMA.rglob("*.schema.json")]
registry = Registry().with_resources(
    (d["$id"], Resource(contents=d, specification=DRAFT202012)) for d in docs
)

r03 = json.loads((SCHEMA / "records" / "r03_deposit.schema.json").read_text(encoding="utf-8"))
validator = Draft202012Validator(r03, registry=registry)

with open("R3_deposits.jsonl", encoding="utf-8") as fh:
    for line_no, line in enumerate(fh, start=1):
        for error in validator.iter_errors(json.loads(line)):
            print(line_no, "/".join(map(str, error.absolute_path)) or "(record)", error.message)
```

Any validator that implements draft 2020-12, including `unevaluatedProperties`, `if`/`then` and `dependentRequired`, can be used instead.

## Conventions

### Requirement levels

Each field definition carries two annotations, which validators ignore:

* `x-ctres-req` is `M` (mandatory), `C` (conditional) or `O` (optional), as in the field tables of §4.
* `x-ctres-condition`, on every `C` field, states the condition in words.

`M` fields are listed in `required`. A `C` field is enforced with `if`/`then` where the condition can be read from the record itself, for example: a withdrawal requires `requested_at`, `paid_at`, `destination_rule`, `approved_by` and `approved_at`; an R1 location of type `provider_balance`, `emoney_account` or `mobile_money_collection`, or with custody model `omnibus_at_provider`, requires `provider_id`; an R8 exception that is `resolved` requires `resolved_at`. Where the condition depends on the jurisdiction profile or on another record (for example `tax_lines`, `limit_check`, `account_fx_rate`), the schema treats the field as optional and the condition is applied by validation outside JSON Schema.

Fields the R3/R4 table marks as mandatory for withdrawals only are annotated `C`, with the condition "mandatory where direction is withdrawal". Within a rail module, `M` means mandatory whenever the module applies.

### Records are closed

A record may carry only the fields its schema defines (`unevaluatedProperties: false`), so that a misspelt field name is reported rather than silently ignored. Rail-module fields are permitted only for the rail they belong to: a card deposit cannot carry `tx_hash`. Rail values map to modules as follows; `carrier_billing` uses the `mobile_money` module.

| `rail` | Module | `instrument_detail` (R2) | Fields added to R3/R4 |
|---|---|---|---|
| `card` | card | `bin`, `last_four`, `card_token` | none |
| `bank_transfer` | bank_transfer | `account_number_masked`, `scheme`, `instant_payment_key_type` | none |
| `emoney` | emoney | `wallet_account_id_masked`, `funding_source_type` | none |
| `mobile_money`, `carrier_billing` | mobile_money | `phone_number_hash`, `mobile_operator_id` | none |
| `voucher` | voucher | `voucher_serial`, `voucher_issuer_id` | `retail_point_id` |
| `cash` | cash | `retail_point_id`, `retail_point_type` | `retail_point_id`, `cashier_ref` |
| `virtual_asset` | virtual_asset | `chain`, `address`, `unique_deposit_address`, `link_source` | `chain`, `off_chain_movement`, `tx_hash`, `block_time`, `confirmations`, `counterparty_address`, `counterparty_type` |

R1 locations of type `crypto_wallet` add `chain`, `temperature`, `key_control_model` and, for warm and cold wallets, `approvers`. R5 checks of type `blockchain_analytics` may add `exposure_categories`.

### Values

* Amounts are decimal strings matching `^-?\d+(\.\d+)?$`, never JSON numbers (§8.2).
* Timestamps are ISO 8601 with an explicit offset, `Z` or `±hh:mm` (§8.2). Dates are `YYYY-MM-DD`.
* Currencies are ISO 4217 codes; virtual assets are identified by asset and chain or contract, for example `USDT-ERC20` (§8.2).
* `credited_amount` in R3 and R4 is positive for a credit to the player account and negative for a debit.
* A player is identified by `player_ref_scope` and `player_ref` together (§4.2). R5 carries `subject_ref_scope` when the subject is a player.
* Masked account numbers carry `*` in place of hidden characters; phone numbers appear only as hexadecimal hashes (§12).

### Visible gaps

Where a control left no record, the field carries the literal value `not_recorded` instead of being omitted (§3). Only the following fields accept it:

| Record | Fields |
|---|---|
| R1 | `opened_at`, `ownership_evidence_ref` |
| R2 | `verified_at`, `verified_by` |
| R3, R4 | `initiated_at`, `settled_at`, `credited_at`, `ledger_entry_ref`, `check_ids`, `requested_at`, `paid_at`, `approved_by`, `approved_at`; and `limit_check`, whose enumeration in §4.3 includes `not_recorded` |
| R5 | `version`, `evidence_ref` |
| R6 | `approved_by`, `approved_at`, `rail_reference` |
| R7 | `reviewed_by` |
| R9 | `notified_at` |
| R10 | `authorising_authority`, `licence_ref`, `due_diligence_completed_at`, `data_locations`, `evidence_ref` |
| R12 | `filed_at` |

Record identifiers, amounts and other enumerations never accept it. An empty `check_ids` list states that no check applied; `not_recorded` states that a check may have applied but left no record.

### Report references under confidentiality

R12 never carries the content of a suspicious transaction report (§4.12). Where confidentiality rules keep R12 out of periodic packages, the manifest carries `report_reference_counts` instead: counts and timeliness by report type.

## Examples

* `examples/annex-c-*.json` are the five example records of Annex C. The values Annex C shows are kept; the mandatory fields Annex C omits for brevity are added.
* `examples/r01-*.json` to `examples/r12-*.json` are synthetic records for an invented operator. Several record types have more than one example, to show the rail modules and conditional fields.
* `examples/manifest-*.json` are a periodic package manifest and a correction that supersedes it.
* `examples/profile-xj-*.json` are profiles for **XJ — Example Jurisdiction**, which is **fictional**. XJ is an ISO 3166-1 user-assigned code; every authority, register, threshold and deadline in these files is invented, and `fictional` is set to `true`. The second profile, XJ-N, shows inheritance from a base profile with overrides.

No example describes a real operator, player or jurisdiction.

## Running the tests

```sh
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python tests/validate_examples.py
```

The test checks that every schema is a valid draft 2020-12 document with the expected `$id`, that every field definition carries a description citing a section and its requirement annotations, that every example is valid, and that deliberately broken copies of the examples are rejected. The same test runs on every push and pull request (`.github/workflows/validate.yml`).

## Comments

Comments are welcome from authorities, operators, payment providers, auditors and anyone else.

* Open an issue at <https://github.com/ctres-standard/schema/issues>, or
* write to <hello@ctres.org>.

Comments on the text of the Standard belong in [ctres-standard/spec](https://github.com/ctres-standard/spec). See [CONTRIBUTING.md](CONTRIBUTING.md) for how changes are proposed.

Maintained by the editor of the Standard (see <https://ctres.org/governance/>).

## Licence

The schema, examples and tests in this repository are licensed under the [Apache License, Version 2.0](LICENSE). The text of the Standard is licensed separately under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
