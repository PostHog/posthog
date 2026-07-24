# Seed data script

Run this via `hogli dev:shell-plus -y -- -c "<script>"`.
It creates 6 batch imports covering all statuses and edge cases.

## Contents

The script seeds six batch imports, each exercising a distinct state:

1. Running — actively processing with partial progress
2. Completed — all parts done, no lease
3. Failed — parse error with high backoff attempt
4. Paused — expired lease
5. Waiting to start — running status but no lease
6. Retrying — running with active backoff

- [Edge cases covered](#edge-cases-covered) — table mapping each record to its key diagnostic signal

```python
from products.managed_migrations.backend.models.batch_imports import BatchImport
from posthog.models import Team, User
from datetime import timedelta
from django.utils.timezone import now

team = Team.objects.first()
team2 = Team.objects.all()[1] if Team.objects.count() > 1 else team
user = User.objects.first()

# 1. Running — actively processing with progress
BatchImport.objects.create(
    team=team,
    created_by_id=user.id,
    status=BatchImport.Status.RUNNING,
    lease_id='worker-abc123',
    leased_until=now() + timedelta(minutes=25),
    status_message='Processing S3 files from mixpanel export',
    display_status_message='Import in progress',
    import_config={
        'source': {'type': 's3', 'bucket': 'acme-mixpanel-export', 'region': 'us-east-1', 'prefix': 'events/2024/'},
        'data_format': {'type': 'json_lines', 'skip_blanks': True, 'content': {'type': 'mixpanel'}},
        'sink': {'type': 'capture'},
        'import_events': True,
        'generate_identify_events': True,
    },
    secrets={'access_key': 'test-key', 'secret_key': 'test-secret'},
    state={
        'parts': [
            {'key': 'events/2024/01/', 'current_offset': 50000, 'total_size': 50000},
            {'key': 'events/2024/02/', 'current_offset': 50000, 'total_size': 50000},
            {'key': 'events/2024/03/', 'current_offset': 32000, 'total_size': 50000},
            {'key': 'events/2024/04/', 'current_offset': 0, 'total_size': 50000},
            {'key': 'events/2024/05/'},
        ]
    },
)

# 2. Completed
BatchImport.objects.create(
    team=team,
    created_by_id=user.id,
    status=BatchImport.Status.COMPLETED,
    status_message='Successfully imported 1.2M events',
    display_status_message='Import completed successfully',
    import_config={
        'source': {'type': 's3', 'bucket': 'acme-amplitude-data', 'region': 'eu-west-1', 'prefix': 'export/'},
        'data_format': {'type': 'json_lines', 'skip_blanks': True, 'content': {'type': 'amplitude'}},
        'sink': {'type': 'capture'},
        'import_events': True,
    },
    secrets={'access_key': 'test-key', 'secret_key': 'test-secret'},
    state={
        'parts': [
            {'key': 'export/part-001.jsonl', 'current_offset': 100000, 'total_size': 100000},
            {'key': 'export/part-002.jsonl', 'current_offset': 100000, 'total_size': 100000},
            {'key': 'export/part-003.jsonl', 'current_offset': 100000, 'total_size': 100000},
        ]
    },
)

# 3. Failed — parse error
BatchImport.objects.create(
    team=team2,
    created_by_id=user.id,
    status=BatchImport.Status.FAILED,
    status_message='JSONDecodeError at offset 45232 in part events/march.jsonl',
    display_status_message='Import failed due to invalid data format',
    import_config={
        'source': {'type': 's3', 'bucket': 'customer-events-bucket', 'region': 'us-west-2', 'prefix': 'events/'},
        'data_format': {'type': 'json_lines', 'skip_blanks': False, 'content': {'type': 'captured'}},
        'sink': {'type': 'capture'},
    },
    secrets={'access_key': 'test-key', 'secret_key': 'test-secret'},
    state={
        'parts': [
            {'key': 'events/january.jsonl', 'current_offset': 80000, 'total_size': 80000},
            {'key': 'events/february.jsonl', 'current_offset': 80000, 'total_size': 80000},
            {'key': 'events/march.jsonl', 'current_offset': 45232, 'total_size': 80000},
        ]
    },
    backoff_attempt=5,
    backoff_until=now() + timedelta(hours=1),
)

# 4. Paused — with expired lease
BatchImport.objects.create(
    team=team2,
    created_by_id=user.id,
    status=BatchImport.Status.PAUSED,
    status_message='Paused by support staff for investigation',
    display_status_message='Import paused',
    lease_id='worker-xyz789',
    leased_until=now() - timedelta(hours=2),
    import_config={
        'source': {'type': 's3_gzip', 'bucket': 'big-data-import', 'region': 'ap-southeast-1', 'prefix': 'compressed/'},
        'data_format': {'type': 'json_lines', 'skip_blanks': True, 'content': {'type': 'mixpanel'}},
        'sink': {'type': 'capture'},
    },
    secrets={'access_key': 'test-key', 'secret_key': 'test-secret'},
    state={
        'parts': [
            {'key': 'compressed/batch-001.jsonl.gz', 'current_offset': 25000, 'total_size': 100000},
        ]
    },
)

# 5. Waiting to start — running status but no lease
BatchImport.objects.create(
    team=team,
    created_by_id=user.id,
    status=BatchImport.Status.RUNNING,
    status_message='Queued for processing',
    display_status_message='Waiting to start',
    import_config={
        'source': {'type': 'url_list'},
        'data_format': {'type': 'json_lines', 'skip_blanks': True, 'content': {'type': 'captured'}},
        'sink': {'type': 'capture'},
    },
    secrets={'placeholder': 'true'},
)

# 6. Retrying — running with backoff
BatchImport.objects.create(
    team=team,
    created_by_id=user.id,
    status=BatchImport.Status.RUNNING,
    status_message='Retrying after transient S3 error: SlowDown',
    display_status_message='Import temporarily paused, retrying soon',
    lease_id='worker-retry-001',
    leased_until=now() + timedelta(minutes=10),
    import_config={
        'source': {'type': 's3', 'bucket': 'massive-import', 'region': 'us-east-1', 'prefix': 'data/'},
        'data_format': {'type': 'json_lines', 'skip_blanks': True, 'content': {'type': 'captured'}},
        'sink': {'type': 'capture'},
    },
    secrets={'access_key': 'test-key', 'secret_key': 'test-secret'},
    state={
        'parts': [
            {'key': 'data/chunk-1.jsonl', 'current_offset': 500000, 'total_size': 500000},
            {'key': 'data/chunk-2.jsonl', 'current_offset': 500000, 'total_size': 500000},
            {'key': 'data/chunk-3.jsonl', 'current_offset': 120000, 'total_size': 500000},
            {'key': 'data/chunk-4.jsonl', 'current_offset': 0, 'total_size': 500000},
            {'key': 'data/chunk-5.jsonl'},
            {'key': 'data/chunk-6.jsonl'},
        ]
    },
    backoff_attempt=2,
    backoff_until=now() + timedelta(minutes=3),
)

print(f'Seeded {BatchImport.objects.count()} batch imports')
```

## Edge cases covered

| Record | Status             | Key diagnostic signal                             |
| ------ | ------------------ | ------------------------------------------------- |
| 1      | Running            | Active lease, partial progress (2/5 parts done)   |
| 2      | Completed          | All parts done, no lease                          |
| 3      | Failed             | Parse error, high backoff attempt                 |
| 4      | Paused             | Expired lease (leased_until in past)              |
| 5      | Running (no lease) | `display_status` derived as `waiting_to_start`    |
| 6      | Running (backoff)  | Active backoff, partial progress (2/6 parts done) |
