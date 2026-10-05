# Changelog

Versions follow §13 of the Standard: `MAJOR.MINOR` is the version of the Standard the schema implements, and `PATCH` corrects the schema without changing the record model. See [README.md](README.md#versioning).

## 1.0.0 — 2026-10-05

Draft for consultation. First release, implementing CTRES v1.0, universal edition (2 October 2026).

### Added

* `schema/common.schema.json`: decimal strings, timestamps with an explicit offset, dates, durations, ISO 4217 codes and virtual-asset identifiers, identifiers, the player key pair, the `not_recorded` marker for visible gaps (§3), fees and tax lines, and shared enumerations.
* `schema/rail_modules.schema.json`: rail modules for card, bank transfer and instant payments, e-money, mobile money and carrier billing, vouchers, cash, and virtual assets (§6).
* `schema/payment.schema.json` and `schema/records/r01_funds_location.schema.json` to `r12_report_reference.schema.json`: the twelve record types of §4, with conditional requirements expressed as `if`/`then` where the record itself shows the condition.
* `schema/manifest.schema.json`: the package manifest of §8.2, including supersession of an earlier package and counts of report references where R12 is withheld (§4.12).
* `schema/profile.schema.json`: the structure of a jurisdiction profile (§5): versioning and effective dates, status, inheritance from a base profile, indexed units, and one parameter block for each row of the §5 table.
* `examples/`: the five Annex C examples, completed with the fields Annex C omits; synthetic examples of every record type; two manifests; and two profiles for the fictional jurisdiction XJ.
* `tests/validate_examples.py` and a GitHub Actions workflow that runs it.
