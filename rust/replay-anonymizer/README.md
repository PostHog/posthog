# posthog-replay-anonymizer

PII scrubber for rrweb session-replay events: text/URL redaction, native image blur, and canvas/`cv` neutralization. This is the scrub core behind PostHog's ml-mirror pipelines.

Consumers:

- `replay-anonymizer-node` (this workspace) wraps it as a Neon addon for the Node ingestion workers.
- The MLHog training pipelines consume it from crates.io.

Behavior is pinned by the JSON fixtures under `tests/fixtures/`, shared with the Node addon's Jest suite. Scrubbing operates on untrusted input and may panic on pathological payloads; callers that must fail closed should wrap calls in `catch_unwind` under `panic = "unwind"`.

## Releasing

Publishing to crates.io is automated by `.github/workflows/publish-replay-anonymizer-crate.yml`:

1. Bump `version` in `Cargo.toml` and merge to master.
2. Tag the merged commit `posthog-replay-anonymizer/v<version>` and push the tag.

The workflow verifies the tag matches the crate version and publishes via crates.io trusted publishing (GitHub OIDC, no long-lived token).
