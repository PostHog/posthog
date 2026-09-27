# Feature Flag Rules v2 contract

This package defines Feature Flag Rules v2 configuration, definitions, response, management diagnostic and event contracts, plus the canonical evaluation corpus.
Contract package 2.2.0 contains config schema 1.0.0, registry 2.0.0, corpus 1.1.0, wire schemas/fixtures 1.0.0, and person boolean evaluation corpus 1.0.0.
The contract version is independent of the test harness package version.

The package does not enable config writes or runtime evaluation.
It reserves number and object values for later writer support.

## Terminology and OpenFeature translation

These are PostHog configuration names compatible with OpenFeature's evaluation and provider interfaces.
OpenFeature does not prescribe this configuration schema; person assignment, experiments, rule types, and variant weights are PostHog vocabulary choices.

default_value is the flag default; the caller default is supplied to the SDK accessor.
On a normal no-match result, a configured flag default of false wins over a caller default of true.
A null flag default delegates to the caller default.
On abnormal execution, OpenFeature returns the caller default regardless of the configured flag default.

Each variants[].weight is a percentage of subjects enrolled by the rule, and the weights sum to exactly 100.
The separate rollout_percentage controls enrollment into the rule.

Person flags may explicitly set assign_by to person or omit it.
Group flags declare aggregation_group_type_index (including index 0) and must omit assign_by on every rule; the schema enforces this so assignment uses the flag aggregation key.

Experiment rules require an integer experiment_id linking an Experiment row.
An experiment_id of null is invalid in this contract.
Non-experiment variant splits are reserved for a possible future extension; their evaluation reason and exposure semantics are not defined here.

rollout_miss means a terminal miss under on_rollout_miss: return_default.
A continuing miss moves evaluation to the next rule and contributes neither a reason code nor metadata from the missed rule (including rule_id and condition_index) to the final result. The final result uses the terminating rule's reason and metadata, or no_rule_match if no rule terminates.
no_rule_match means no rule produced a terminal result, including when targeting matched but rollout missed with continue.
dependency_error covers unknown, cyclic, and otherwise unresolvable dependencies.

The OpenFeature mapping also depends on the provider's evaluation-context binding.
missing_group_key maps to INVALID_CONTEXT when required group membership is missing from additional context fields, even if a person targetingKey is present.
Only a provider that binds the group key to OpenFeature targetingKey uses TARGETING_KEY_MISSING when that field is missing.
Percentage rollout inclusion maps to TARGETING_MATCH by contract choice; OpenFeature also describes pseudorandom assignment with SPLIT and permits custom reasons.

## Package contents

- schemas/config.schema.json contains the JSON Schema 2020-12 config contract.
- registries/literals.json owns shared protocol literals, semantic constraints, and the OpenFeature reason mapping.
- fixtures/config/valid contains configs that the schema must accept.
- fixtures/config/invalid contains configs that the schema must reject.
- corpus/hash_sha1_60_v1.json contains exact sha1_60_v1 vectors, white-box threshold and variant boundary vectors, and v1-to-v2 seed parity inputs.
- corpus/v1_evaluation.json contains lock-down fixtures for the frozen version 1 evaluation arm.
- corpus/legacy_projection.json records how a version 1 outcome projects into each response protocol version.
- schemas/hash_sha1_60_v1.schema.json, schemas/v1_evaluation.schema.json, and schemas/legacy_projection.schema.json are the companion schemas for the corpus files.
- corpus/v2_boolean_evaluation.json contains the person boolean evaluation corpus, and schemas/v2_boolean_evaluation.schema.json is its companion schema.
- manifest.json assigns stable fixture and case IDs and declares the compatibility policy.
- SHA256SUMS records the SHA-256 digest for each package file except itself.

In the config and corpus schemas, objects marked with x-posthog-open-object accept arbitrary keys by design; every other object is closed.
The marker documents this choice for the contract tests; additionalProperties defines how those keys are validated.

The config schema enforces all constraints that the standard can express, including the 20-level object-value depth limit.
Depth counts object and array containers, with the returned object at level 1; scalar leaves add no level.
The registry also identifies constraints that need a semantic or parser-level validator, such as unique rule IDs and variant keys, and exact variant weight totals.

Docker releases include contracts/ directly. MANIFEST.in also includes this contract in Python source distributions for source-artifact verification.
It does not install the contract as wheel package data; consumers should pin the repository files or use the source distribution or Docker image.

## Component versions

Each artifact carries its own component version in manifest.json.
The config schema stays at 1.0.0 because contract 2.0.0 does not change its published bytes or accepted configs.
The literal registry is 2.0.0: it removes the four unused management warning codes (`EXPERIMENT_VALUE_COLLISION`, `SDK_REMOTE_FALLBACK_REQUIRED`, `SDK_EXPERIMENT_CONTEXT_MISSING`, `LEGACY_PROJECTION_LIMITED`) from the `warning_codes` published in registry 1.0.0 (contract 1.2.0), which the compatibility policy classifies as a major change; the five remaining codes are unchanged.
The corpus files and their companion schemas are corpus version 1.1.0.
Contract package 2.1.0 adds config fixtures for the targeted-release and percentage-rollout family; it changes no published schema, registry, corpus or fixture bytes.

## Corpus rules

Every corpus case has a stable ID that manifest.json declares under its file.
Adding, removing, or renaming a case requires a manifest change.

Expected values are hand-derived from the algorithm definition and the frozen version 1 evaluator.
Hash expectations were calculated with an independent SHA-1 implementation, never generated from a production evaluator.
The meta-tests recompute every hash vector, so an expectation cannot change silently.

A published corpus version is immutable.
Changing any expected value, including a hash vector, a version 1 outcome, or a projection cell, requires a new corpus version and a review explanation of why the previous expectation was wrong or superseded.
Additive cases may join a new minor corpus version; a changed expectation is a major corpus change.

Hash arithmetic is defined in corpus/hash_sha1_60_v1.json.
The contract value of hash01 converts both the 60-bit integer and the scale to binary64 before one division.
Consumers must parse decimal hash01 literals with correctly rounded binary64 conversion, including 17-digit literals.
Check the accompanying hash01_binary64_hex before consuming the corpus; a best-effort JSON float parser can otherwise move a boundary case.
Thresholds are rollout_percentage / 100 computed in binary64, and variant boundaries accumulate left to right in binary64 in stored order.

## Empty identifiers in the frozen version 1 arm

The Rust `/flags` service is the server-side version 1 reference; there is no remaining Python server-side v1 evaluator.
The frozen arm pins its behavior as verified on 2026-09-10 at [PostHog/posthog f57417de1c412fe55187540f392def4e2aef48b3](https://github.com/PostHog/posthog/blob/f57417de1c412fe55187540f392def4e2aef48b3/rust/feature-flags/src/flags/flag_matching.rs#L2160).
A deliberate change to that behavior requires a new corpus version.

Version 1 accepts an empty `distinct_id`; a missing field is invalid.
Its rollout and variant hash accessor returns 0.0 without calling SHA-1 for the empty identifier.
The inclusive rollout comparison therefore matches even at 0 percent, and a 50/50 variant split selects the first stored variant.
Holdouts do call SHA-1: the empty identifier hashes `holdout-` to 0.9268829483920294, outside a 92 percent holdout and inside a 93 percent holdout.
Version 2 never enters rollout, holdout, or variant assignment with an empty identifier.

`hash_evidence` always records SHA-1 arithmetic.
For the empty-identifier rollout and variant cases it shows the counterfactual arithmetic result; `expected` records the reference's 0.0-path outcome, and each note explains the difference.
For holdouts the recorded arithmetic is the hash the reference actually uses.

`local_evaluation` describes the local evaluator contract: `conclusive` requires the expected value, `inconclusive` requires fallback without a local value, and `remote_only` pins reference behavior that local evaluators do not yet implement; an evaluator implementing it must match.
The empty-identifier cases are `remote_only` because [posthog-python a1002c577e7c69e3f321f8f0832ee037316135a3](https://github.com/PostHog/posthog-python/blob/a1002c577e7c69e3f321f8f0832ee037316135a3/posthog/feature_flags.py#L116) hashes the prefix (plus the variant salt) locally and ignores holdouts.
Its public local-only flag API returns false at 0 and 62 percent, test for the stored control/test 50/50 split, and true for both holdout fixtures.
These are known SDK divergences, not inconclusive results or evidence of automatic fallback; the 92 percent holdout result happens to agree.

## Version and integrity policy

A published contract version is immutable.
Publish a new contract version to correct or extend a published contract.
Do not change a published version in place.

SHA256SUMS uses raw file bytes.
It has one lowercase SHA-256 digest, two spaces, a relative POSIX path, and one line feed per entry.
Entries use bytewise path order.

To pin this contract, record the source revision, the contract version, the corpus version, and the SHA-256 digest of SHA256SUMS.
Verify each file against SHA256SUMS before use.

After editing rules/response_presence.json, regenerate the derived terminal-reason branches of the presence and called-context schemas:

```sh
python3 <repo>/bin/update-feature-flag-rules-v2-presence-schemas.py
```

After editing contract files and updating manifest.json, regenerate the checksum index from any working directory:

```sh
python3 <repo>/bin/update-feature-flag-rules-v2-checksums.py
```

Run `python -m pytest tests/test_feature_flag_rules_v2_contract.py tests/test_feature_flag_rules_v2_corpus.py tests/test_feature_flag_rules_v2_wire.py` from the repository root to verify the manifest, fixtures, corpus, and checksums.


## Wire artifacts and validation boundaries

- `schemas/definitions_entry.schema.json` selects v1 for absent/1 `filters.version`, or references the frozen config schema for v2. The entry's row `version` is independent. Row `version` and `ensure_experience_continuity` retain their existing nullable types. Existing v1 filters are opaque in this schema; this package does not redefine legacy evaluation semantics.
- `schemas/definitions_v2.schema.json` describes the mixed-version definitions feed, including its required cohort map and optional boolean `minimal_flag_called_events`. Unsupported config versions or v2 semantic fields require per-flag remote fallback in auto mode and an unsupported result in strict local mode.
- `schemas/flags_response_v3.schema.json` is the exact producer schema. Its raw-byte digest is pinned in the manifest and tests. `schemas/flags_response_v3_presence.schema.json` adds the terminal-reason presence matrix from `rules/response_presence.json`. The companion also requires the failure envelope flag whenever a record failed and rejects an `experiment_id` alongside `has_experiment: false` in any record; `has_experiment: true` alone does not imply an unambiguous experiment ID. Validate against both, then check map-key equality and recursive seed absence. A schema-only success does not establish a valid producer response.
- `schemas/management_warning.schema.json` describes a diagnostic with a required warning code from the registry's five `warning_codes` and optional presentation `detail` and field `attr`. `schemas/management_error.schema.json` preserves the management validation-error envelope (`type`, `code`, `detail`, `attr`); error codes remain endpoint-owned. These artifacts do not install a warning response envelope or an acknowledgement protocol.
- `schemas/feature_flag_called_context.schema.json` and `schemas/experiment_exposure_properties.schema.json` describe **closed property projections**, not entire capture envelopes. The generic call supports v1 diagnostics and v2 terminal context. A malformed-split diagnostic may retain config version 2 and the split reason while omitting the whole rule/experiment attribution tuple; a partly populated tuple is rejected. Direct exposure requires the complete v2 experiment-split tuple, SDK origin and `locally_evaluated`, and forbids holdout and forced-variant context. Scan the full event for assignment seeds before extracting the projection; normal capture identity, library, group and optional transport properties remain outside it.
- `fixtures/wire/` contains producer fixtures, separate tolerant-reader expectations, and full-event transport examples. A case deep-copies a named template, removes existing members by JSON Pointer, and then sets members by JSON Pointer (the parent must exist). Invalid cases declare the validation layer, keyword and instance path; reader cases separately declare producer validity; optional message fragments disambiguate required fields. `schema`, `presence`, `semantic` and `seed` are fixture validation layers, not new wire error codes.

Definitions retain canonical rule and holdout assignment seeds because local evaluation needs them. Evaluation responses and events prohibit assignment seeds recursively, including inside arrays, diagnostic conditions and opaque transport objects. The response's `flags` map keys are user-defined flag names, so names such as `seed` are allowed; every record and the rest of the envelope are still scanned. Likewise, the immediate keys of an event's `$groups`, `$set` and `$set_once` maps are customer-chosen group type and person property names; their values are still scanned.

Producer and reader contracts serve different purposes. Missing split context is invalid producer output, but a reader preserves a usable value and emits no experiment exposure. Known fields with wrong JSON types produce a per-record parse error and leave siblings usable. Unknown fields are ignored. A record without `value` uses the old-server `variant ?? enabled` interpretation, config version 1, and no carried-over v2 context. Reader expectations never loosen producer validation. Reader and event fixtures are contract data; they do not run SDK execution or activate capabilities.

The first event release permits only booleans and non-empty strings in the response property. Reserved number/object response-schema cases do not enable writers or event emission. Equal-valued arms remain separate analytical identities through their variant keys. A holdout, pause, rollout miss, default, missing or failed result cannot produce a direct exposure.

Future accepted/rejected wire-contract changes require a new major wire component version and a new major package version; additive fixture cases require a new minor fixture version and a new minor package version. Wire schema `$id`s are stable URLs without embedded versions, matching the exact producer schema; the component version is carried by `manifest.json` and the checksum index, so load one package version per schema registry. A future major wire revision publishes new schema files under new paths and `$id`s rather than reusing these.

The source distribution includes every indexed artifact and the checksum utility. Verify a build against the checkout with:

```sh
uv build --sdist
python3 bin/update-feature-flag-rules-v2-checksums.py --verify-sdist dist/posthog_sdk_test_harness-<harness-version>.tar.gz
```

The verifier reads the archive without extraction, requires its checksum index to match the checkout, and checks exact file coverage and every digest against that index.

## Person boolean evaluation corpus

Contract 2.2.0 adds `corpus/v2_boolean_evaluation.json` and its schema as a separate 1.0.0 component.
The frozen v1 corpus, hash/variant vectors, schemas, registry, and wire fixtures keep their published bytes and versions.

Each case supplies a full config, explicit person identifier and property completeness, team timezone, exact-matching setting, and fixed evaluation time.
The core consumes the resolved person distinct ID without device or experience-continuity overrides.
A complete property map can establish absence; a partial map cannot establish absence for an unknown key.
An unavailable map fails only when evaluation reaches a predicate.
Predicates are ANDed in stored order and short-circuit on a conclusive miss or an error.
Negation applies once to conclusive results; an absent or null `negation` means false.
Malformed regex syntax and backtracking failures are evaluation errors, including under negation; this avoids turning an invalid pattern into a successful negative match.
This is stricter than v1's invalid-pattern non-match behavior and does not change v1 expectations.
A consumer may compile patterns when it loads a config, but an invalid pattern in a predicate that evaluation never reaches is not a parse error; the error surfaces only when evaluation reaches the predicate.
Other operators reuse the existing property language, including null presence, case handling, semver normalization, and team-timezone date comparisons.

### Regex coverage

The shared regex cases use ASCII literals, `^`/`$` anchors, and ordinary capturing groups, with case-sensitive search semantics: an unanchored pattern may match a substring.
`not_regex` complements a successful search result; predicate `negation` then complements that conclusive result once more.
The unmatched `[` is a syntax error for both operators, and neither operator nor predicate negation converts that error to a match.
These cases require no lookaround, backreferences, or engine-specific extensions.
They do not define the complete regex dialect accepted by a consumer.

Actual regex execution failures must remain errors, but this language-neutral corpus does not prescribe an execution budget or require a particular pattern to exhaust it.
Engine-specific lookaround support and backtracking-limit tests belong with the implementation, where the engine and limit are known.
A passing shared corpus alone does not establish support for those extensions.

### Date comparisons

Both the person property and filter value resolve to instants before comparison, using the same `context.now` and IANA `context.timezone`.
`is_date_exact` compares instants for equality, including the time of day; it does not compare calendar dates or truncate to midnight.
`is_date_before` and `is_date_after` use strict `<` and `>` comparisons, so equality matches neither.
The `explicit_exact_matching` setting affects the separate `exact` operator, not these date operators.

- A timestamp with `Z` or an explicit offset denotes that instant regardless of the team timezone.
- A bare `YYYY-MM-DD` denotes midnight in the team timezone. A date and time without an offset denotes that wall-clock time in the team timezone.
- Numeric person properties, including numeric strings, denote Unix epoch seconds.
- Relative strings have the form `-?N[hdwmy]`, with an integer magnitude below 10,000. Both `1d` and `-1d` mean one day ago; the optional minus does not reverse the direction.
- To resolve a relative value, first convert `context.now` to the team timezone and take its local wall clock. Subtract the magnitude there: hours, days, or seven-day weeks use wall-clock arithmetic; months and years subtract one calendar month or year at a time, clamping the day to the last valid day at each step. Preserve the time of day and fractional seconds. For example, two months before March 31, 2024 is January 29, 2024 after the intermediate February clamp.
- Interpret the resulting wall clock in the team timezone, then convert it to an instant. During a fall-back overlap, choose the earlier instant. A spring-forward gap has no instant and produces a non-match. An unparseable property value also produces a non-match. Predicate negation applies afterwards to these conclusive non-matches.

For `relative_dst`, `2024-03-31T12:00:00Z` is 14:00 in Oslo. Subtracting `-1d` gives March 30 at 14:00 local, or `2024-03-30T13:00:00Z`: 23 elapsed hours earlier.
The paired miss case rejects `2024-03-30T12:00:00Z`, even though it is on the same local date and exactly 24 elapsed hours earlier.
The fall-back cases similarly distinguish a 25-hour calendar day and the two occurrences of an overlapping wall-clock time; the gap case rejects a nonexistent time.

These rules follow the reference consumer's [relative-date resolution](https://github.com/PostHog/posthog/blob/157973cc642c31bceb8fe00c566bb8aed0a3a38f/rust/feature-flags/src/properties/relative_date.rs) and [date comparisons](https://github.com/PostHog/posthog/blob/157973cc642c31bceb8fe00c566bb8aed0a3a38f/rust/feature-flags/src/properties/property_matching.rs).
The corpus uses the explicit formats above; it does not require the reference consumer's additional best-effort absolute-date formats.

### Terminal results and consumer scope

`expected` is exhaustive: compare every field and reject unexpected fields.
Success with a null value delegates to the caller default; success with false remains a configured result.
`no_rule_match` carries no rule, while terminal matches and rollout misses carry the original UUID, kind, and zero-based index.
Errors carry no successful value or rule context.
The evaluation error kinds `missing_context`, `invalid_property`, and `invalid_regex` refine the registry's `error` reason code and share its OpenFeature mapping.
Parse errors reject the document before evaluation: `malformed` for a document the config schema rejects, and `unsupported` for an unknown config version, the registry's `unknown_version_result`.
The corpus does not define a new response protocol.

Hash evidence records UTF-8 bytes, the real SHA1 digest, its first 60 bits, and binary64 hash/threshold bits.
The meta-tests independently recompute these values with Python hashlib and binary64 arithmetic.
Identifiers truncate to 200 Unicode scalar values without normalization; predicate values remain intact.
The truncation and normalization cases use thresholds that separate the correct digest from UTF-8 byte, UTF-16 code unit, NFC, and NFD mistakes.
Empty identifiers are rollout misses even at 100%, so `on_rollout_miss` decides whether evaluation continues or returns the default; nonempty 100% bypasses hashing.
At 0%, the inclusive zero-hash edge remains included.
`white_box` rows replay through a consumer's private test-only hook that passes `white_box.hash01_binary64_hex` straight into the rollout threshold comparison, skipping identifier hashing; each row records equal, below, or next-binary64-above threshold evidence.
They supplement real digest cases and must not become a public override API.

Consumers must report the `ordering`, `properties`, `context`, `errors`, `hashing`, `white_box`, `eligibility`, and `parser` families separately.
Eligibility cases run through the existing request boundary and require omission, without calling the core.
Parser cases require whole-document rejection, separately from evaluation support.
The existing published variant/experiment/holdout/group/dependency vectors remain outside this component's evaluator scope.
A passing boolean corpus does not establish those families or production reachability.
