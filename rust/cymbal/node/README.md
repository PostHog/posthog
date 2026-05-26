# @posthog/cymbal

Node.js client package for Cymbal's gRPC ingestion API.

Edit this package when changing generated TypeScript bindings or Node-side client exports for `ProcessExceptionBatch`. Regenerate from the Rust protobufs instead of editing generated files by hand.

Validate from `rust/cymbal`:

```sh
pnpm --dir node run generate
pnpm --dir node typecheck
```
