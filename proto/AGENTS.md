# Proto definitions

## Adding or modifying RPCs

When you add or modify an RPC or message type in `personhog/` protos, you **must** update all downstream consumers before considering the change complete:

### 1. Python generated stubs

```bash
bin/generate_personhog_proto.sh
```

Then update:

- `posthog/personhog_client/proto/__init__.py` — add/remove re-exports for any new/removed message types
- `posthog/personhog_client/client.py` — add/remove wrapper methods for any new/removed RPCs
- `posthog/personhog_client/fake_client.py` — implement the new method for test use

### 2. Node.js generated stubs

```bash
cd nodejs && pnpm run generate:personhog-proto
```

Then update:

- `nodejs/src/ingestion/personhog/client.test.ts` — add a default stub to the `SERVICE_DEFAULTS` object for any new RPC

### 3. Rust

No codegen step needed (tonic regenerates on `cargo build`), but you must:

- Implement the RPC in `rust/personhog-replica/` (storage layer + service handler)
- Wire it through `rust/personhog-router/` (backend, router, and service layers)
- Add tests (see Rust test conventions in `rust/personhog-replica/AGENTS.md`)
