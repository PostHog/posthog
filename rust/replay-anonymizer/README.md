# posthog-replay-anonymizer

PII scrubber for rrweb session-replay events: text/URL redaction, native image blur, and canvas/`cv` neutralization. This is the scrub core behind PostHog's ml-mirror pipelines.

Consumers:

- `replay-anonymizer-node` (this workspace) wraps it as a Neon addon for the Node ingestion workers.
- The MLHog training pipelines consume it from crates.io.

Behavior is pinned by the JSON fixtures under `tests/fixtures/`, shared with the Node addon's Jest suite. Scrubbing operates on untrusted input; the public entry points contain panics and convert them to errors, so callers fail closed (drop the message) without their own `catch_unwind`. Under `panic = "abort"` that backstop cannot run — builds that must fail closed need `panic = "unwind"`.

Offline consumers (JSONL of individual events rather than Kafka messages) get a dedicated surface: `anonymize_line` scrubs one line (bare event or `["window_id", event]` tuple), `AllowLists::from_json_bytes` loads the shipped `{ text, url }` document and `AllowLists::default()` embeds the production default lists, and the default `typed-parse` feature adds `parse_scrubbed_event` — scrub-then-parse to a typed rrweb AST (envelope, DOM tree, mutations, interactions) with `cv` payloads transparently decompressed. The Node addon builds with `default-features = false`, so none of the typed surface exists on the ingestion hot path.

## Releasing

Publishing to crates.io is automated by `.github/workflows/publish-replay-anonymizer-crate.yml`: bump `version` in `Cargo.toml` in your PR, and on merge to master the workflow publishes any version not yet on crates.io via trusted publishing (GitHub OIDC, no long-lived token). No tags involved.

If crate code changes in a PR without a version bump, CI posts a reminder comment on the PR. If un-bumped crate changes still reach master (say the version got taken by a PR that merged first), the publish run fails loudly instead of silently skipping; bump the version in a follow-up PR.
