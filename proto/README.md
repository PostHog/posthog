# Proto Definitions

Language-agnostic protobuf definitions for PostHog services.

## Structure

```text
proto/
├── buf.yaml
├── cymbal/               # Cymbal internal services
│   └── resolution/v1/    # Exception-level symbol resolution
├── ingestion/            # Event ingestion
│   └── worker/v1/        # Consumer → worker streaming ingest transport
├── kafka_assigner/       # Kafka partition assignment
├── personhog/            # Person data service
│   ├── types/v1/
│   ├── replica/v1/
│   └── service/v1/
└── prometheus/           # Prometheus remote write
    └── v1/               # Remote write transport
```

## Consumers

| Proto             | Rust                                           | Python                                                   | Node.js                                                     |
| ----------------- | ---------------------------------------------- | -------------------------------------------------------- | ----------------------------------------------------------- |
| `cymbal/`         | `rust/cymbal-proto` (auto via tonic)           | —                                                        | —                                                           |
| `ingestion/`      | `rust/ingestion-worker-proto` (auto via tonic) | —                                                        | `nodejs/src/common/generated/ingestion-worker` (checked in) |
| `personhog/`      | `rust/personhog-proto` (auto via tonic)        | `posthog/personhog_client/proto/generated/` (checked in) | `nodejs/src/common/generated/personhog` (checked in)        |
| `kafka_assigner/` | `rust/kafka-assigner-proto` (auto via tonic)   | —                                                        | —                                                           |
| `prometheus/`     | `rust/prometheus-rw-proto` (auto via tonic)    | —                                                        | —                                                           |

## Updating protos

1. Edit `.proto` files in the relevant directory
2. Regenerate language bindings for affected consumers (see table above)
3. Commit generated files — CI rejects stale stubs

### Python stubs (personhog only)

```bash
bin/generate_personhog_proto.sh
```

Only needed when `personhog/` protos change. Requires `grpcio-tools` and `protoletariat` (`uv sync`).

If you added or removed **message types**, update the re-exports in `posthog/personhog_client/proto/__init__.py`.
If you added or removed **RPCs**, update the wrapper methods in `posthog/personhog_client/client.py`.

### Rust

No action needed — Rust bindings regenerate on `cargo build`.

## CI

`.github/workflows/ci-proto.yml` runs on proto changes:

- `buf lint` — style and naming
- `buf breaking` — backwards compatibility against `master`
- Python codegen staleness check
