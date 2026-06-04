# Cymbal worker

Rust Temporal worker skeleton for Cymbal workflows and activities.
It also subscribes to the embedding worker result topic and starts a sample Temporal workflow for Error tracking stacktrace/fingerprint embedding results.
The sample processing activity prints the raw Kafka message.

## Local development

`hogli start` runs this worker when the Error tracking intent is enabled.
The worker runs locally via `bin/start-rust-service cymbal-worker`; only Temporal itself runs in Docker through the `temporal` compose profile.

To configure your dev environment for Error tracking:

```bash
hogli dev:setup
hogli start
```

For a direct smoke test without the full dev environment, start Temporal and the worker separately:

```bash
docker compose -f docker-compose.dev.yml --profile temporal up -d temporal temporal-ui
bin/wait-for-docker temporal
bin/start-rust-service cymbal-worker
```

Then start the sample workflow from the Temporal admin tools container:

```bash
docker compose -f docker-compose.dev.yml run --rm temporal-admin-tools \
    temporal workflow start \
    --namespace default \
    --task-queue cymbal-worker \
    --type cymbal_echo_workflow \
    --workflow-id cymbal-echo-test \
    --input '{"message":"hello from cymbal-worker"}'
```

The workflow calls `cymbal_echo_activity` and returns the message unchanged.
Temporal UI is available at http://localhost:8081.

Embedding result handling listens to `document_embedding_results` using the `cymbal-worker` consumer group.
Only messages with `product: "error_tracking"` and `document_type: "stacktrace"` or `"fingerprint"` start `cymbal_process_embedding_result_workflow`.
