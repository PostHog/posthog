---
name: testing-mcp-tools-locally
description: >
  Set up the local dev environment, seed data, and API keys to test the staff-only managed migrations
  MCP tools (managed-migrations-support-list, managed-migrations-support-get) end to end.
  Use when testing batch import support tooling, debugging MCP tool responses or discovery
  (tools not appearing), or verifying the support API before deploying.
  Covers the discovery gate: hidden scope, is_staff, user:read, and why wildcard keys and OAuth never work.
---

# Testing managed migrations MCP tools locally

## Prerequisites

The dev environment must be running with Docker services healthy.
The batch import support API and MCP tools require:

- A staff user (`is_staff = True`)
- A Personal API Key carrying **both** `batch_import_support:read` and `user:read`, explicitly
- Postgres migrations applied (ClickHouse not required)

Why both scopes: the backend accepts `batch_import_support:read` alone,
but MCP tool discovery verifies staffness via `/api/users/@me/` and hides the tools (fail-closed) when the key cannot make that call.
A `*` wildcard does **not** substitute for either — the discovery gate requires the hidden scope explicitly, and the backend's `INTERNAL` scope handling rejects wildcard keys outright.
For the production setup flow, see [docs/support-mcp-tools.md](../../docs/support-mcp-tools.md).

## 1. Start the dev environment

```bash
hogli start -d
hogli wait
```

If `hogli wait` fails on `migrate-persons-db` or `migrate-behavioral-cohorts`,
those are optional separate databases — ignore them.
If it fails on `migrate-postgres`, check Docker port forwarding (see troubleshooting below).

## 2. Run Postgres migrations

```bash
hogli migrations:run
```

ClickHouse migration failures are fine — batch imports only need Postgres.

## 3. Verify DB connectivity from the Django shell

```bash
hogli dev:shell-plus -y -- -c "
from posthog.models import Team, User
print(Team.objects.first(), User.objects.first())
"
```

If this fails with `connection refused` on port 5432, see troubleshooting below.

## 4. Seed batch import test data

Use `hogli dev:shell-plus` to create `BatchImport` records in various states.
The `secrets` field is an `EncryptedJSONStringField` — empty `{}` serializes to null
and violates the NOT NULL constraint; always pass a non-empty dict.

```python
from products.managed_migrations.backend.models.batch_imports import BatchImport

BatchImport.objects.create(
    team=team,
    created_by_id=user.id,
    status=BatchImport.Status.PAUSED,
    import_config={
        'source': {'type': 's3', 'bucket': 'test', 'region': 'us-east-1', 'prefix': 'data/'},
        'data_format': {'type': 'json_lines', 'skip_blanks': True, 'content': {'type': 'mixpanel'}},
        'sink': {'type': 'capture'},
    },
    secrets={'access_key': 'test', 'secret_key': 'test'},
    state={'parts': [
        {'key': 'part-1', 'current_offset': 50000, 'total_size': 50000},
        {'key': 'part-2', 'current_offset': 10000, 'total_size': 50000},
        {'key': 'part-3'},
    ]},
)
```

See `references/seed-data.md` for a full seeding script covering all statuses.

**Important:** the local `batch-import-worker` process will pick up `RUNNING` records
and may modify their status (e.g. pausing them due to config validation errors).
To keep records stable for testing, either stop the worker or use `COMPLETED`/`FAILED`/`PAUSED` statuses.

## 5. Make your user staff and mint test keys

Mint **fresh** keys rather than editing scopes on an existing one —
the MCP server caches a key's scopes per token, so edited scopes can serve stale results.

```python
from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

me = User.objects.first()
me.is_staff = True; me.save()

def mint(user, scopes):
    token = generate_random_token_personal()
    PersonalAPIKey.objects.create(user=user, label=str(scopes)[:40], secure_value=hash_key_value(token), scopes=scopes)
    return token

print(mint(me, ["batch_import_support:read", "user:read"]))
```

To test the negative cases of the discovery gate, also mint:
a `["*"]` key (tools must NOT appear),
a `["batch_import_support:read"]` key without `user:read` (tools must NOT appear — staff lookup fails closed),
and the full pair on a non-staff user (tools must NOT appear).

## 6. Test the API directly

```bash
# List all batch imports
curl -H "Authorization: Bearer <token>" \
     http://localhost:8010/api/managed_migrations_support/ | jq

# Get detail for a specific import
curl -H "Authorization: Bearer <token>" \
     http://localhost:8010/api/managed_migrations_support/<uuid>/ | jq
```

## 7. Test via MCP

**Run the Hono server, not `pnpm run dev`.**
The wrangler worker (`pnpm run dev`, port 8787) proxies `/mcp` to **production** `mcp.us.posthog.com` unless `MCP_HONO_URL` is set,
so local keys get `401 Invalid API key`.
The Hono server serves MCP directly against the local API:

```bash
cd services/mcp
cp .dev.vars.example .dev.vars   # POSTHOG_API_BASE_URL=http://localhost:8010
pnpm run dev:hono                # serves http://localhost:3001/mcp
```

**Authenticate with the PAT as a Bearer header, never the OAuth flow.**
The hidden scope is structurally absent from OAuth — signing in through the inspector's OAuth login can never surface these tools.

The Hono server runs exec mode: `tools/list` returns a single `exec` tool,
and real tools are discovered and invoked through it.
Test with the MCP Inspector CLI:

```bash
# Discovery — should list both support tools for the staff key, none for the others
npx @modelcontextprotocol/inspector --cli http://localhost:3001/mcp \
  --header "Authorization: Bearer <token>" \
  --method tools/call --tool-name exec --tool-arg "command=search managed-migrations-support"

# Invocation — end-to-end through Django
npx @modelcontextprotocol/inspector --cli http://localhost:3001/mcp \
  --header "Authorization: Bearer <token>" \
  --method tools/call --tool-name exec --tool-arg "command=call managed-migrations-support-list {}"
```

Expected discovery matrix:

| key                                                         | tools visible                    |
| ----------------------------------------------------------- | -------------------------------- |
| staff user, `batch_import_support:read` + `user:read`       | both                             |
| staff user, `*` only                                        | none                             |
| staff user, `batch_import_support:read` without `user:read` | none (staff lookup fails closed) |
| non-staff user, both scopes                                 | none (and direct API calls 403)  |

The interactive Inspector UI (`http://localhost:6274`) also works —
paste the PAT as the Bearer token in connection settings instead of using its OAuth login.

## Troubleshooting

### 401 "Invalid API key" from localhost:8787

You're talking to the wrangler worker, which proxies `/mcp` to production — your local key is invalid there.
Use the Hono server on port 3001 (see step 7), or set `MCP_HONO_URL=http://localhost:3001` in `.dev.vars`.

### Tools don't appear for a key that should see them

Check, in order:

1. The key carries `batch_import_support:read` **explicitly** — `*` does not match hidden scopes.
2. The key also carries `user:read` (or `*`) — the discovery staff check reads `/api/users/@me/` and fails closed.
3. The key's user has `is_staff = True`.
4. The key was minted with those scopes from the start — the MCP server caches scopes per token, so mint a fresh key instead of editing an existing one.

### Port 5432 not reachable from host

The `posthog-db-1` Docker container may have stale port mappings
(container created days ago without the current port binding config).
Fix by force-recreating:

```bash
docker compose -f docker-compose.dev.yml -f docker-compose.profiles.yml \
  up -d --force-recreate db
```

Verify: `nc -z 127.0.0.1 5432` should succeed.

### `secrets={}` causes NOT NULL violation

`EncryptedJSONStringField` encrypts the value — an empty dict serializes to null.
Always pass a non-empty dict: `secrets={'placeholder': 'true'}`.

### Batch import worker modifies seeded records

The local `batch-import-worker` process automatically claims `RUNNING` records.
If it encounters a config validation error (e.g. missing `skip_blanks`),
it will pause the import with a detailed Rust backtrace in `status_message`.
Stop the worker or seed with non-`RUNNING` statuses to prevent this.

### The gates, end to end

A request passes through two independent layers:

1. **MCP discovery** (presentation): a tool requiring an OAuth-hidden scope surfaces only when the key explicitly carries the scope AND `/api/users/@me/` confirms `is_staff` — otherwise it is hidden, fail-closed (`services/mcp/src/lib/staff-only-tools.ts`).
2. **Django enforcement** (the security boundary): `IsAuthenticated` + `IsStaffUser` + `APIScopePermission` with `scope_object = "INTERNAL"` and `batch_import_support:read`. Sessions need staffness only; PATs need staffness plus the explicit scope; `*`-only keys always 403.
