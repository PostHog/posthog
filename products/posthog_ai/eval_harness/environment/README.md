# Reusable local evaluation environments

Prepare a persistent PostHog project from saved events and metric definitions. This runs the normal dev app and verifies the restored data through HogQL. It does not run an agent, create a scout, or start an evaluation. No model API keys are needed.

## Prepare a devbox from your laptop

After the normal one-time `hogli devbox:setup`, run this from your laptop's PostHog checkout. Replace the example bucket, path and checksum with the published dataset:

```bash
hogli devbox:prepare-eval-env -n eval1 \
  --bundle s3://example-eval-datasets/environments/example/v1/environment.tar.gz \
  --sha256 REPLACE_WITH_PUBLISHED_SHA256 \
  --aws-profile eval-data
```

The command downloads the archive using your laptop's AWS login, verifies its SHA-256, then creates or starts the named devbox. It copies the archive over SSH and imports it into the normal PostHog app. Events go to ClickHouse and saved metric definitions go to PostgreSQL. On the first import, dates shift to the current time. The command prints the project URL after import and app readiness checks succeed.

Use your usual AWS profile instead of `eval-data`, or omit `--aws-profile` for the default credential chain. An SSO profile needs its normal login first, such as `aws sso login --profile eval-data`. The laptop needs permission to read that object; the devbox needs no S3 access or AWS credentials. The bucket is selected by the URI, not by repository configuration.

No manual download is needed. The laptop uses a private temporary directory and removes it after success or failure. Failed downloads stop before devbox creation. The devbox retains a verified archive and receipt, including the original S3 URI and checksum. Reruns download and verify the pinned object again, then reuse the existing remote archive and project without adding events or shifting dates again.

S3 mode uses `boto3`, which is included in the PostHog Python environment. A standalone hogli installation can use `uv tool install --python 3.13 --with boto3 ./tools/hogli` from the repository root; it does not need the local PostHog stack.

A local archive also works: `hogli devbox:prepare-eval-env -n eval1 --bundle /private/path/environment.tar.gz`. Keep it outside Git or in an ignored directory. Its SHA-256 is checked on both machines; an optional `--sha256` also checks a published digest. Local inputs need no AWS login.

The devbox must have this command's importer code. Before the change is on master, add `--ref YOUR_PUBLISHED_BRANCH` to the same command. This resolves a local Git revision to an exact commit and checks it out on the devbox. It refuses to replace a dirty checkout or change code under a running app. Without `--ref`, the existing remote checkout stays in place.

Use `--state-dir .flox/cache/another-eval-environment` for another dataset or to recover from a failed import. Keep that directory for future reruns. A new state directory creates a separate project; it does not delete or reset a previous project. `--user-id ID` selects the local owner when the devbox has several users, and `--target-cutoff ISO_TIMESTAMP` selects an explicit date reference. Login credentials, when created, stay in a private file on the devbox; the command prints its path, never its contents.

If setup prints a credentials-file path, connect with `hogli devbox:ssh -n eval1` and read that file to sign in to the local PostHog app. Otherwise, use the devbox's existing PostHog login.

## Restore an environment

From a standard PostHog devbox with its dependencies installed:

```bash
products/posthog_ai/eval_harness/prepare-devbox /private/path/environment.tar.gz
```

An unpacked folder containing `environment.json` works too. The command validates the bundle before starting the app, reuses a healthy local app, and leaves services running. It prints the project URL, receipt path, and a private credentials-file path if it created a local login. With several active local users, pass `--user-id ID` to select the owner.

The default state directory is `.flox/cache/eval-environment`. Keep it for reruns: the receipt pins the input, database, project, identity namespace, and target cutoff. A successful rerun verifies and reuses that project without appending events. It also checks that metrics and the project's Drop Events transformation remain unchanged. The transformation prevents normal capture from adding events to this snapshot project.

Use `--state-dir /private/path/another-import` to create a separate project or recover from a failed import. A pending or failed receipt is not resumed, and the command does not delete a partially created project. Do not delete a receipt to retry into the same project. After a startup failure before import, rerun with the same state directory.

The command only accepts local development database settings. It never stops another checkout's app. If the running app belongs to another checkout and this checkout needs migrations, it refuses the import: start a compatible normal app before retrying. For its own checkout, it waits for startup migrations and can apply the normal forward PostgreSQL migrations. The workspace retains private startup and migration logs.

## Publish a private bundle to S3

Upload each dataset version once, from a laptop with write access to the private bucket you choose:

```bash
aws s3 cp /private/path/environment.tar.gz \
  s3://example-eval-datasets/environments/example/v1/environment.tar.gz \
  --profile eval-data
```

Share that S3 URI and the SHA-256 printed by `pack` through a private channel. Use a new path for each version. Keep versions available for the comparison period and public access blocked. Publishers need write access; people running the laptop setup command need read access. Neither requires S3 permissions on the devbox. The setup command does not create buckets, upload data, or change access policies.

## Restore directly from S3 on an existing machine

If the machine running the importer already has AWS read access, it can download directly:

```bash
products/posthog_ai/eval_harness/prepare-devbox \
  s3://example-eval-datasets/environments/example/v1/environment.tar.gz \
  --sha256 REPLACE_WITH_PUBLISHED_SHA256
```

The SDK uses the devbox's role automatically; the AWS CLI is not required to download. If your machine instead uses a named [AWS profile](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html), add `--aws-profile eval-reader`. For an SSO profile, log in first with your usual AWS setup, such as `aws sso login --profile eval-reader`.

The checksum is required for S3. It pins the exact archive even if someone replaces the object at that path. Downloads stream to a private temporary file in the state directory, with a 2 GiB compressed-size limit. A complete, matching download is saved as `download-<sha256>.tar.gz`; existing archive checks then validate its contents before app startup or import. Failures remove partial downloads and leave the database untouched. Public HTTP URLs and presigned URLs are not accepted.

Repeat runs recheck and reuse the private cached archive without contacting S3. A changed or symbolic-link cache file is rejected. The first import records the S3 URI and archive checksum in its private receipt; later reuse preserves that original provenance. Local archives can also use `--sha256`; unpacked folders continue to use their manifest checksums.

Use `--aws-profile` to select a named profile in `~/.aws/config`. The repository wrapper clears ambient shell variables, including exported AWS credentials and `AWS_PROFILE`; named profiles and their normal local credential/SSO files survive because the home directory is preserved. Without the flag, the SDK uses its default credential chain inside that environment. S3 downloads use AWS endpoints independently of the app's `OBJECT_STORAGE_*` settings and configured endpoint overrides. No model keys are needed.

## Build a bundle

Use the canonical `EnvironmentEvent` and `EnvironmentMetric` models with `EVENT_TABLE` and `METRIC_TABLE`. These helpers write the exact Parquet column types, including JSON-encoded properties and timezone-aware timestamps. Arbitrary query-export Parquet schemas are not accepted.

This complete example uses invented data and writes only to `/tmp`:

```bash
.codex/with-flox python - <<'PY'
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from products.posthog_ai.eval_harness.environment.schema import (
    EVENT_TABLE, METRIC_TABLE, EnvironmentEvent, EnvironmentMetric,
)

folder = Path("/tmp/posthog-environment-example")
folder.mkdir(mode=0o700, exist_ok=True)
cutoff = datetime(2030, 6, 4, 12, tzinfo=UTC)
EVENT_TABLE.write(folder / "events.parquet", [EnvironmentEvent(
    uuid=UUID("00000000-0000-4000-8000-000000000001"),
    event="example_action",
    distinct_id="example-user",
    timestamp=cutoff - timedelta(hours=1),
    created_at=cutoff - timedelta(minutes=59),
    properties={"$current_url": "https://example.com/demo", "duration": 3},
)])
METRIC_TABLE.write(folder / "metrics.parquet", [EnvironmentMetric(
    id=UUID("00000000-0000-4000-8000-000000000002"),
    created_at=cutoff - timedelta(days=1),
    name="example_actions",
    description="Count example actions.",
    definition={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
    referenced_table_names=["events"],
    status="approved",
)])
PY

.codex/with-flox python -m products.posthog_ai.eval_harness.environment pack \
  --events /tmp/posthog-environment-example/events.parquet \
  --metrics /tmp/posthog-environment-example/metrics.parquet \
  --source-cutoff 2030-06-04T12:00:00Z \
  --name example-environment \
  --output /tmp/posthog-environment-example/environment.tar.gz
```

`--events` accepts several files. Exact duplicate event rows with the same UUID are combined; conflicting rows are rejected. `--metrics` is optional. `--timezone` defaults to `UTC` and sets the restored project's timezone. The archive contains only the manifest, data files, and complete `SHA256SUMS`; it never replaces an existing output. Files are private, and archive extraction rejects links, special files, and paths outside the bundle.

## Time and scope

The source cutoff is an exclusive bound for event `timestamp` and `created_at`. Metric timestamps must be at or before the source cutoff. Version 1 captures metric state at that same checkpoint.

On the first restore, the target cutoff defaults to UTC now. Every typed timestamp shifts by `target_cutoff - source_cutoff`, retaining microsecond precision. Pass `--target-cutoff 2030-07-04T12:00:00Z` for a fixed reference time. Reruns retain the original target; they do not move the data forward as wall time advances. Use a new state directory for a new reference time.

Dates inside SQL, descriptions, or JSON strings shift only when explicitly listed in a `--text-policy` JSON file:

```json
{
  "time_strings": ["2030-06-04T12:00:00Z"],
  "string_replacements": {}
}
```

Declared time strings retain their written precision. A date-only or seconds-only string cannot represent a finer cutoff shift: choose an aligned target cutoff when exact textual query boundaries matter. `string_replacements` applies literal substitutions to restored property and metric text; it is an explicit preparation rule, not an anonymizer.

Version 1 restores events and data-catalog metrics only. It does not reconstruct people, groups, dashboards, insights, external tables, agent state, tasks, or report history. Metrics may reference only `events`; source insight references are unsupported. Event UUIDs, distinct IDs, and source event identity values remain in the saved data, while restored metric IDs and their references receive a project-local namespace. Ensure the chosen event window and metric definitions are sufficient for the task you plan to run.

## Private data

Keep source files, bundles, extracted data, receipts, and credentials outside Git or in an ignored directory. Packing validates structure and checksums; it does not remove sensitive text or identifiers. Review and anonymize real data before sharing it through an approved private channel. Pseudonymized customer-derived data remains private; public repository examples and fixtures must be independently invented. Preparing this project does not authorize uploading its contents through a later evaluation or agent run.
