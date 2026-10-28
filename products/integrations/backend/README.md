# Integrations SDK

The integrations SDK is the only way to read and write `Integration` rows (`posthog/models/integration/model.py`).
The rows move to a separate credentials service soon.
The SDK is a small, closed set of operations, so only its transport changes after the move.

```python
from products.integrations.backend.facade.api import IntegrationManager, IntegrationRecord
```

## Read rows

An accessor fixes the kind, the auth type, or both. Each operation takes `team_id` first and returns rows in the scope of the accessor only.

| Accessor                                 | Rows                                                   | Operations       |
| ---------------------------------------- | ------------------------------------------------------ | ---------------- |
| `IntegrationManager.github.oauth`        | One kind with one auth type                            | Reads and writes |
| `IntegrationManager.stripe.any`          | One kind with every auth type                          | Reads and delete |
| `IntegrationManager.kinds("slack", ...)` | Several kinds with every auth type                     | Reads and delete |
| `IntegrationManager.any`                 | Every row, warehouse source rows too                   | Reads and delete |
| `IntegrationManager.source(kind).token`  | Warehouse source rows of one kind with one auth type   | Reads and writes |
| `IntegrationManager.source(kind).any`    | Warehouse source rows of one kind with every auth type | Reads and delete |

Reads:

- `get(team_id, id)` returns the row, or raises `IntegrationNotFound` when the row is not in the scope.
- `get_many(team_id, ids)` returns `{id: row}` for the ids in the scope.
- `find(team_id, external_id=..., where={...})` returns the oldest matching row or `None`.
- `list(team_id, external_id=..., where={...}, newest_first=False)` and `exists(...)`.
- `list_by_external_id(external_id, team_ids=None)` reads across teams, for example the teams that share one GitHub installation.
- `usages(team_id, id)` returns the PostHog objects that use the row.

`where` compares named config keys for equality, for example `where={"installation_id": "123"}`.
It does not accept lookups (`a__b`), nested values or the keys that the SDK writes (`auth_type`, `warehouse_source_type`), and raises `UnsupportedIntegrationFilter`.
When you need more, add a named method to the SDK.

Each operation has an async form with an `a` prefix: `aget`, `alist`, `aupdate`, and so on.

## Write rows

Only an accessor with one auth type can write, because a new row has exactly one auth type.

- `create(team_id, external_id=..., config=..., sensitive_config=..., created_by_id=...)`.
- `upsert(team_id, external_id, config=..., ...)` returns `(row, created)`. It replaces the config of an existing row. It raises `IntegrationConflict` when the existing row is not in the scope, for example a row with another auth type.
- `update(team_id, id, config_patch=..., config_remove=..., sensitive_config_patch=..., errors=...)` merges a patch. `errors=None` keeps the errors.
- `update_atomically(team_id, id, change)` locks the row, calls `change(row)`, and applies the `IntegrationPatch` that it returns.
- `update_by_external_id(external_id, patch)` patches the rows of every team.

Delete rows with `delete(team_id, id)`. It raises `IntegrationInUse` with the usages when other objects use the row. Pass `ignore_usages=True` to delete it anyway.
`delete_by_external_id(external_id)` deletes the rows of every team.

Do not call `.save()` or `.delete()` on a row, and do not set `row.config[...]`.
`IntegrationRecord` is the Django model now. A later change makes it a frozen record, and those calls stop working.

## Pick an auth type

Each kind supports some of three auth types, and has one default:

| Auth type     | Use it for                                                                                      |
| ------------- | ----------------------------------------------------------------------------------------------- |
| `oauth`       | A connection that the provider manages: an OAuth grant or an app installation                   |
| `token`       | One static secret: an API key, a personal access token, a bot token or a webhook secret         |
| `credentials` | Several typed-in fields: host, user and password, an access key and a secret, a service account |

Use the auth type of the rows that your code can handle.
A kind class has an attribute only for the auth types that the kind supports, so mypy rejects `IntegrationManager.github.credentials`.
Use `.any` only when your code handles every auth type of the kind the same way, for example a picker or a delete.

A row stores its auth type in `config["auth_type"]` only when it is not the default of its kind. The SDK writes that key. Do not write it yourself.

## Add a kind

1. Add the kind to `Integration.IntegrationKind` in `posthog/models/integration/model.py`.
2. Add the kind to `KINDS` in `facade/catalogue.py`, with its default auth type and its other auth types.
3. Run `hogli build:projections --only integration-kinds` and commit `facade/kinds_generated.py`.

The default of a kind is stored data. Do not change the default of a kind that has rows.

Warehouse source kinds are not in the catalogue. The warehouse product registers them at startup with `register_source_kinds`, and callers reach their rows through `IntegrationManager.source(kind)`.
A warehouse source row has `config["warehouse_source_type"]`. The named accessors (`IntegrationManager.stripe.token`) skip these rows, and `IntegrationManager.source(kind)` reads only these rows.

## Report usages

A product that uses integration rows reports them from `products/<product>/backend/integration_usages.py`:

```python
def integration_usages(team_id: int, integration_id: int) -> list[IntegrationUsage]: ...
```

The SDK finds the module on the first call to `usages` or `delete`. Code outside a product calls `register_usage_provider` instead.
The product sets `IntegrationUsage.type` (for example `warehouse_source`, `workflow`, `hog_function`, `batch_export`). The integrations API names these types in its error when a delete finds usages.

## Reference a row from a serializer

Use `IntegrationReferenceField` from `presentation/fields.py` instead of a `PrimaryKeyRelatedField` on `Integration`.
It reads the team from the serializer context, so a row of another team does not exist for the field.
Pass `kinds=[...]` to accept only rows of these catalogue kinds. A field with `kinds` also refuses warehouse source rows, because their config does not have the shape of the kind.

## Why direct model use fails CI

The semgrep rule `.semgrep/rules/devex/integration-model-through-sdk.yaml` finds uses of the model outside the SDK: imports of `Integration`, `Integration.objects`, foreign keys to it, `select_related` and `prefetch_related` on an integration relation, `integration__` lookups, `integration_set`, and `.save()` on a row.
The "Integration model ratchet" step in `.github/workflows/ci-security.yaml` compares the findings per file with `model_access_baseline.txt`.
It fails when a file has more findings than its baseline count, and also when it has fewer.
When you move a file to the SDK, lower its count in the baseline, or remove the line at zero.
Tests, migrations, Django admin, the model and its per-kind adapters (`posthog/models/integration/`) are outside the rule.
