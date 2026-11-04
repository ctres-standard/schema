# CTRES JSON Schema

This repository holds the machine-readable schema of the **Common Transaction Reporting and Evidence Standard (CTRES) v1.1**. CTRES v1.1 is the universal edition of 2 October 2026 (v1.0) extended with two record types for gaming revenue, R13 Gaming Revenue Statement and R14 Venue Count, and the Revenue and levy parameters of a jurisdiction profile (§4.13, §4.14, §5). The schema is the field catalogue referred to in Annex A of the Standard.

The schema is written in JSON Schema draft 2020-12. Section references (§) in the schema and in this document are to the text of the Standard, published at <https://ctres.org> and in the repository [ctres-standard/spec](https://github.com/ctres-standard/spec). Where the schema and the text differ, the text prevails and the difference is a defect in the schema.

Status: open draft for consultation with authorities and industry. Like the Standard, the schema is independent and carries no regulatory force.

## Contents

| Path | Content |
|---|---|
| `schema/common.schema.json` | Shared types: decimal strings, timestamps with an explicit offset, dates, durations, ISO 4217 codes and virtual-asset identifiers, identifiers, the player key pair, the `not_recorded` marker (§3, §8.2), and enumerations used by more than one record. |
| `schema/rail_modules.schema.json` | Rail-module fields (§6): the shape of `instrument_detail` in R2 for each rail, and the fields each rail adds to R1, R3, R4 and R5. |
| `schema/payment.schema.json` | The fields R3 Deposit and R4 Withdrawal share (§4.3, §4.4). |
| `schema/records/r01_funds_location.schema.json` … `r14_venue_count.schema.json` | One schema per record type, R1 to R14 (§4). `r03_deposit` and `r04_withdrawal` apply `payment.schema.json` and fix the direction. `r13_gaming_revenue_statement` and `r14_venue_count` are the two record types added in v1.1 (§4.13, §4.14). |
| `schema/manifest.schema.json` | `manifest.json`, carried by every package (§8.2). |
| `schema/profile.schema.json` | The structure of a jurisdiction profile (§5), including the Revenue and levy block of v1.1. It defines the parameters a profile may set; it contains no profile. |
| `examples/` | Valid examples of every record type, two manifests (a 1.0 package and a 1.1 package) and two profiles. See [Examples](#examples). |
| `tests/validate_examples.py` | Checks the schemas and validates every example; also checks that deliberately broken copies fail. |

Every schema has an `$id` under `https://ctres.org/schema/1.1/`. References between files are relative, so the schemas can be used from a local copy without network access.

## Versioning

The schema follows the versioning rule of §13: major versions change the record model; minor versions add fields, rails or profile parameters; patches correct text.

* The package version is `MAJOR.MINOR.PATCH`. `MAJOR.MINOR` is the version of the Standard the schema implements; this release is **1.1.0**, for CTRES v1.1.
* The `$id` path carries `MAJOR.MINOR` (`/schema/1.1/`). A patch release keeps the same `$id`s and does not change which records are valid, except to correct a schema that contradicts the text. A minor release moves the `$id` path; the 1.0 schemas stay available from the 1.0.x tags of this repository.
* `manifest.json` names the version of the Standard in `standard_version` and the profile in `profile_id` and `profile_version`, so that a package is always validated against the schema version it was produced for. `standard_version` is `1.0` or `1.1`; a package that lists an R13 or R14 file declares `1.1`, and a 1.0 package remains valid against this release.
* Jurisdiction profiles, mapping files and the conformance suite are versioned separately from the schema (§13).

## Scope

The schema expresses the **structural** class of validation in §11: required fields present, types and enumerations valid, conditional fields present where the record itself shows the condition.

The **referential** class (every payment references an instrument in R2 and a provider in R10, every check reference resolves, manifest hashes match the files) spans several records and files and cannot be expressed in JSON Schema. It is implemented by the reference validator in [ctres-standard/validator-lite](https://github.com/ctres-standard/validator-lite).

Profile conformance and completeness (§11) are outside this repository. They are maintained separately as a versioned conformance suite, as §11 describes.

## Conformance levels

§10 of the Standard defines a core and three modules, and four conformance levels that add them in steps. The core is the manifest with R3 Deposit, R4 Withdrawal, R7 Reconciliation Statement and R13 Gaming Revenue Statement; the Custody module is R1, R2, R6, R10 and R11; the Supervision module is R5, R8, R9 and R12; the Venue module is R14.

| Level | Record types required (minimum) | What the authority can check |
|---|---|---|
| `level_1` — Return | manifest + R13 | The return it already receives, in a checkable structure: schema, the arithmetic of each line (`ggr_formula`), one statement per currency |
| `level_2` — Evidence | level_1 + R3, R4, R7; + R14 where any R13 line has `channel` `venue` | The money bridge (§4.13): declared revenue against deposits, withdrawals and balances; the venue win against the count |
| `level_3` — Custody | level_2 + R1, R2, R6, R10, R11 | Where player money sits, who holds it, provider attestations, segregation |
| `level_4` — Supervision | level_3 + R5, R8, R9, R12 | Checks before money moves, exceptions, incidents, reports filed elsewhere: the full model |

* Any record type may be included at any level; the level fixes the minimum set. The manifest declares the level in `conformance_level_declared` (`level_1` to `level_4`, optional). A profile may set the level the authority requires in `parameters.submission.minimum_conformance_level`.
* Field requirements inside a record do not change with the level. At `level_1` and `level_2` a reference to a record type the level does not require (`instrument_id` to R2, `provider_id` to R10, `check_ids` to R5, `location_id` and `venue_id` to R1) is an identifier in the operator's own systems: present in the record, not resolved within the package. `check_ids` may be an empty array at any level.
* The levels are defined by scope. The levels of v1.0 (Records, Structured, Continuous) described delivery maturity and are replaced; delivery is the submission mode of §8.1, `submission_mode` in the manifest (`continuous`, `periodic_package`, `on_demand`, `incident`), and is independent of the level. In a package that declares `standard_version` `1.0`, `conformance_level_declared` keeps its v1.0 meaning.
* Whether the record types of the declared level are present is a structural check of the reference validator (STR-09 in [ctres-standard/validator-lite](https://github.com/ctres-standard/validator-lite)), not of this schema, which sees one record or manifest at a time.

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

`M` fields are listed in `required`. A `C` field is enforced with `if`/`then` where the condition can be read from the record itself, for example: a withdrawal requires `requested_at`, `paid_at`, `destination_rule`, `approved_by` and `approved_at`; an R1 location of type `provider_balance`, `emoney_account` or `mobile_money_collection`, or with custody model `omnibus_at_provider`, requires `provider_id`; an R8 exception that is `resolved` requires `resolved_at`; an R13 statement of kind `correction` requires `corrects_statement_id` and `correction_reason`, and a `period` statement may not carry them; an R14 row for a `slot_machine` requires `meters_start` and `meters_end` unless `meter_source` is `not_recorded`, and `drop_cash` and `fills` where its `win_formula` is `slot_drop_formula`, for a `table` requires `opening_inventory`, `closing_inventory`, `fills`, `credits` and `drop_cash`, for a `counter` requires `opening_inventory` and `closing_inventory`, and for a `venue_total` requires `hard_count`, `soft_count` and `count_variance`; a `table` row names `table_drop_formula` or `profile` as its `win_formula`, and a `slot_machine` row `slot_meter_formula`, `slot_drop_formula` or `profile`; an R14 row carries either `gaming_day` or `period_start` and `period_end`. Fields that are stated together are enforced with `dependentRequired`: in R13, `stakes_bonus` or `winnings_bonus` requires `bonus_measurement`, `bonus_granted` and `bonus_expired`, `fx_rate`, `fx_source` and `fx_at` go together, as do `bonus_granted` and `bonus_expired`, `jackpot_contributions` and `jackpot_payouts`, `network_due_to` and `network_due_from`, and `open_liability_start` and `open_liability_end`. Where the condition depends on the jurisdiction profile or on another record (for example `tax_lines`, `limit_check`, `account_fx_rate`, and in R13 `jurisdiction_category`, `venue_id`, `player_location`, `authority_figure_ref`, the levy fields and whether `fx_rate` is needed at all), the schema treats the field as optional and the condition is applied by validation outside JSON Schema.

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
| R13 | `reviewed_by`, `evidence_ref` |
| R14 | `reviewed_by`; and `meter_source`, whose enumeration in §4.14 includes `not_recorded` |

Record identifiers, amounts and other enumerations never accept it. An empty `check_ids` list states that no check applied; `not_recorded` states that a check may have applied but left no record.

### Report references under confidentiality

R12 never carries the content of a suspicious transaction report (§4.12). Where confidentiality rules keep R12 out of periodic packages, the manifest carries `report_reference_counts` instead: counts and timeliness by report type. The report type `levy_return`, added in v1.1, is the operator's levy or gaming-tax return; an R13 statement cites it through `authority_figure_ref`.

### Gaming revenue statements and venue counts

Two record types added in v1.1 carry what the house won, so that the figure a levy is assessed on can be tested against the money in R3, R4 and R7 (§4.13, §4.14).

* **R13 Gaming Revenue Statement** is one statement per licence, product line, channel, currency and period. It carries stakes and winnings with the recognition rule applied (`stakes_basis`, `winnings_basis`), the bonus, jackpot, network and open-liability components, the operator's GGR with the formula that produced it (`ggr_formula`), and, where the profile's figure of record is the operator's declaration, the levy base, rate and amount. A line of a venue carries `venue_id`, and a line split by player location carries `player_location`, where the profile's aggregation axes call for them. A correction is a separate statement of kind `correction` that replaces an earlier one. Records per bet or round are not part of the Standard; `evidence_ref` cites the platform report behind the line. The schema lists the fields in the order of the field table of §4.13: the core first, which every statement carries (`statement_id`, `statement_kind`, `licence_ref`, `product_line`, `channel`, `period_start`, `period_end`, `currency`, `stakes_basis`, `winnings_basis`, `stakes_cash`, `stakes_refunded`, `winnings_cash`, `ggr_declared`, `ggr_formula`, `prepared_by`, `reviewed_by`, `evidence_ref`), then the conditional and optional fields; the examples follow the same order.
* **R14 Venue Count** is one row per venue, unit and gaming day, or per period where the profile permits. A `slot_machine` row carries the meter set of GLI-11 §3.9.7 at the start and the end (coin in and out, hand-paid jackpots, cancelled credits, progressive payouts paid by the machine and by an attendant, bills, tickets, promotional credits, cashless transfers and games played; a meter the machine does not have is omitted), or the drop where no meter exists (`meter_source` `not_recorded`, `win_formula` `slot_drop_formula`); a `table` or `counter` row carries inventories, fills, credits and drop; a `venue_total` row carries the count-room totals and the variance against the units. `drop_deposit_ref` points at the R6 movement or the R1 cash float the drop was banked to, and R1 locations carry `venue_id` so that a count can be tied to a venue.
* The **Revenue and levy** block of a profile (`parameters.revenue_and_levy`) carries the five parameters and the notes of the §5 table, so that a statement can be computed under the profile rather than read: `levy_formula` (one entry per product line or taxonomy category: the base type, the R13 quantities that enter the base with their sign and any cap, the rate, bands or fixed amount, and for venue lines the win formula per unit type), `recognition` (`stakes_basis` and `winnings_basis`, as R13 carries them), `period_and_filing` (period, cut-off, due date, collector, channel, form and figure of record), `negative_periods` (rule and netting scope) and `aggregation` (axes and the product taxonomy), then `notes`, free text keyed by subject. Bonus, refund, chargeback, jackpot and tax treatments are terms of the formula, not separate switches. The block is optional; where present it carries `levy_formula`, `recognition` and `period_and_filing`, and the profile declares `ctres_version` `1.1`. In outline:

  ```json
  "revenue_and_levy": {
    "reading": "stated",
    "levy_formula": [{
      "applies_to": ["*"], "base_type": "ggr",
      "terms": [{"quantity": "stakes_cash", "sign": "+"}, {"quantity": "stakes_bonus", "sign": "+"},
                {"quantity": "stakes_refunded", "sign": "-"}, {"quantity": "winnings_cash", "sign": "-"},
                {"quantity": "winnings_bonus", "sign": "-"},
                {"quantity": "bonus_granted", "sign": "-", "cap": {"share_of": "stakes_cash", "share": "0.20"}}],
      "rate": "0.20",
      "venue_win_formulas": {"slot_machine": "slot_meter_formula", "table": "table_drop_formula"}
    }],
    "recognition": {"stakes_basis": "placed", "winnings_basis": "credited"},
    "period_and_filing": {"period": "month", "cut_off": "00:00 local", "due": "20th of the following month",
                          "collector": "tax_authority", "figure_of_record": "operator_declaration"},
    "negative_periods": {"rule": "carry_forward", "netting_scope": "product_class"},
    "aggregation": {"axes": ["product_line", "channel"], "taxonomy": {"ref": "...", "version": "..."}},
    "notes": {"stake_scope": "...", "bonus_treatment": "...", "source": "..."}
  }
  ```

  `base_type` is `ggr`, `turnover`, `fixed_per_unit`, `commission`, `fee_band` or `prize_pool`. `terms[].quantity` is one of the fifteen decimal quantities of R13 (`stakes_cash` to `open_liability_end`) and `sign` is `+` or `-`; a cap is a share of another quantity (`share_of`, `share`) or an amount (`amount`, `currency`). A formula carries exactly one of `rate`, `bands` (`up_to`, with `null` for the top band, and `rate`) and `fixed_amount` (`amount`, `currency` and `per`: `slot_machine`, `table`, `counter`, `venue` or `month`); a `fixed_per_unit` formula carries `fixed_amount`, any other carries `terms`. The values of `venue_win_formulas` are those of R14 `win_formula`, restricted per unit type as in R14. `period` is `gaming_day`, `week`, `month`, `quarter` or `year`; `collector` is `tax_authority`, `regulator`, `both` or `other`; `figure_of_record` is `operator_declaration` or `authority_computation`; `negative_periods.rule` is `carry_forward`, `floor_zero` or `none` with `netting_scope` `line`, `product_class` or `licence`; `aggregation.axes` are `product_line`, `jurisdiction_category`, `channel`, `venue`, `player_location`, `currency` and `brand`; `notes` has the keys `stake_scope`, `bonus_treatment`, `refunds_and_voids`, `chargebacks_and_bad_debts`, `jackpot_and_pool_contributions`, `taxes_in_base`, `evidence_linkage`, `land_based` and `source`. Every object is closed.
* A package that lists an R13 or R14 file declares `standard_version` `1.1` in its manifest. Packages without them may keep `1.0`.

The money bridge between R13 and R3, R4 and R7, the consistency of R14 with the venue line of R13, and the match between `jurisdiction_category` and the profile's taxonomy span several records and belong to validation outside JSON Schema (§11).

## Examples

* `examples/annex-c-*.json` are the five example records of Annex C. The values Annex C shows are kept; the mandatory fields Annex C omits for brevity are added.
* `examples/r01-*.json` to `examples/r14-*.json` are synthetic records for an invented operator. Several record types have more than one example, to show the rail modules and conditional fields. The R13 examples are an online casino line with bonus play, jackpots, an open liability, the player location and the authority's own figure, a venue line for the gaming machines of one venue, and a correction of a sports-betting line; the R14 examples are a slot machine with meter readings, a table with inventories and drop, and a venue total with count-room figures.
* `examples/manifest-*.json` are a periodic package manifest for a 1.0 package, a correction that supersedes it, and a 1.1 package that lists R13 and R14 files.
* `examples/profile-xj-*.json` are profiles for **XJ — Example Jurisdiction**, which is **fictional**. XJ is an ISO 3166-1 user-assigned code; every authority, register, threshold, rate and deadline in these files is invented, and `fictional` is set to `true`. XJ 1.1.0 carries the Revenue and levy block and supersedes XJ 1.0.0, which the 1.0 manifests cite. The second profile, XJ-N, shows inheritance from a base profile with overrides.

No example describes a real operator, player or jurisdiction.

## Running the tests

```sh
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python tests/validate_examples.py
```

The test checks that every schema is a valid draft 2020-12 document with the expected `$id` and that the package holds the expected number of schemas, that every field definition carries a description citing a section and its requirement annotations, that every example is valid, and that deliberately broken copies of the examples are rejected. The same test runs on every push and pull request (`.github/workflows/validate.yml`).

## Comments

Comments are welcome from authorities, operators, payment providers, auditors and anyone else.

* Open an issue at <https://github.com/ctres-standard/schema/issues>, or
* write to <hello@ctres.org>.

Comments on the text of the Standard belong in [ctres-standard/spec](https://github.com/ctres-standard/spec). See [CONTRIBUTING.md](CONTRIBUTING.md) for how changes are proposed.

Maintained by the editor of the Standard (see <https://ctres.org/governance/>).

## Licence

The schema, examples and tests in this repository are licensed under the [Apache License, Version 2.0](LICENSE). The text of the Standard is licensed separately under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
