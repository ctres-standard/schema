# Contributing

Thank you for reviewing the CTRES schema. This document describes how changes are proposed and accepted.

## Where a change belongs

* **The text of the Standard is the source of truth.** A change to the record model (a new field, a new enumeration value, a change from optional to mandatory) is first a change to the text, proposed in [ctres-standard/spec](https://github.com/ctres-standard/spec). The schema follows once the text is settled.
* **A schema that contradicts the text** is a defect. Report it here, quoting the section and the schema path.
* **Jurisdiction profiles** for real jurisdictions are maintained by the editor with the authorities concerned (§5, §13) and are not accepted into this repository. Corrections to a profile go to the editor at <hello@ctres.org>. This repository defines only the structure of a profile, and its example profiles describe fictional jurisdictions.
* **Validation beyond structure** — referential checks across records — belongs in [ctres-standard/validator-lite](https://github.com/ctres-standard/validator-lite).

## How to propose a change

1. Open an issue describing the problem, the section of the Standard concerned, and the change proposed. For small corrections a pull request alone is enough.
2. Substantive changes are published for comment before adoption (§13). The editor states in the issue whether a change is substantive.
3. Pull requests are reviewed by the editor. Where a change affects the text, it is merged only after the corresponding text change.

## Requirements for a pull request

* `python tests/validate_examples.py` passes.
* Every field definition has a `description` that states its purpose and cites the section of the Standard, an `x-ctres-req` annotation (`M`, `C` or `O`), and, for `C`, an `x-ctres-condition`. The test enforces this.
* Enumerations are spelled exactly as in the text.
* A conditional requirement that can be read from the record itself is expressed with `if`/`then`; one that depends on a profile or on another record is stated in `x-ctres-condition` only.
* New or changed behaviour is covered by an example, or by a broken copy in `tests/validate_examples.py` that must fail.
* Examples are synthetic. They contain no personal data and describe no real operator, player or jurisdiction. Example profiles use a fictional jurisdiction with an ISO 3166-1 user-assigned code and set `fictional` to `true`.
* The change is recorded in `CHANGELOG.md`.
* Text is in English, in a plain and precise register.

## Versioning

Versions follow §13 and are described in [README.md](README.md#versioning). A change that alters which records are valid is not a patch, unless it corrects a schema that contradicts the text.

## Licence of contributions

Unless you state otherwise, any contribution you submit for inclusion in this repository is licensed under the Apache License, Version 2.0, as set out in section 5 of the [License](LICENSE).

## Contact

General enquiries and comments that cannot be made public: <hello@ctres.org>. The repository is maintained by the editor of the Standard (see <https://ctres.org/governance/>).
