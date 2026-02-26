# Proto Definitions

Language-agnostic protobuf definitions for PostHog services.

## Structure

```text
proto/
├── buf.yaml              # Linting and breaking change config
└── personhog/            # Person data service
    ├── types/v1/         # Shared message types
    ├── replica/v1/       # Read API
    └── service/v1/       # Public API
```

## Language Bindings

| Language | Package                                                                        | Notes                                         |
| -------- | ------------------------------------------------------------------------------ | --------------------------------------------- |
| Rust     | [`rust/personhog-proto`](/rust/personhog-proto)                                | Generated at build time via tonic             |
| Python   | [`posthog/personhog_client/proto/generated`](/posthog/personhog_client/proto/) | Checked-in stubs generated via `grpcio-tools` |

### Python (Django)

Generated stubs live in `posthog/personhog_client/proto/generated/` and are checked into git.
Regenerate after changing `.proto` files:

```bash
bash bin/generate_personhog_proto.sh
```

Requires `grpcio-tools` (`uv pip install grpcio-tools`).

The client wrapper is at `posthog/personhog_client/client.py` with a rollout gate at `posthog/personhog_client/gate.py`.

## CI Checks

Proto changes trigger `.github/workflows/ci-proto.yml`:

- **Lint**: Style and naming conventions
- **Breaking**: Detects backwards-incompatible changes against `master`
- **Python codegen**: Verifies checked-in stubs match what the `.proto` files produce

## Adding a New Proto

1. Add/modify `.proto` files in the appropriate directory
2. Run `buf lint proto/` locally (if buf installed) or let CI validate
3. Regenerate Python stubs: `bash bin/generate_personhog_proto.sh`
4. Commit the generated files — CI will reject stale stubs
5. Rust bindings regenerate automatically on build
