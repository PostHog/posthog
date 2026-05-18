# LLM analytics agent guide

Repo-wide conventions live in [`../../AGENTS.md`](../../AGENTS.md) — kea over hooks, generated
API over `api.get`, `ph_scoped_capture` in Celery, etc. Read that first.

This file is only for rules that are specific to `products/llm_analytics/`
(and to the query runners in `posthog/hogql_queries/ai/`).

**If you don't know the folder yet, read [README.md](./README.md) first**
for the directory map. Skip it if you already know where things live —
it's orientation, not a rulebook.

## Update both query runners together

`LLMTrace` and `LLMTraceEvent` are built by two parallel query runners:

- `posthog/hogql_queries/ai/trace_query_runner.py` (single trace read)
- `posthog/hogql_queries/ai/traces_query_runner.py` (list of traces)

Both define their own `_map_trace` and `_map_event`. Neither imports
from the other. Any time you add, remove, or rename a field on
`LLMTrace` or `LLMTraceEvent`, or change how an event is shaped into
either, **change both runners in the same PR** and cover the change in
`posthog/hogql_queries/ai/test/`. The type checker will not catch drift
here.

The same rule applies to routing via `ai_events` vs `events`. If one
runner adopts a new code path, the other needs the matching change so
single-trace and list reads don't diverge.

## Product docs go under `docs/`

Rollout plans, migration plans, and product ADRs belong in
`products/llm_analytics/docs/`, not at the product root.

## Custom `@action` methods need explicit scope action lists

`ScopeBasePermission` (in `posthog/permissions.py`) only resolves
`<scope_object>:read` / `<scope_object>:write` from its built-in defaults
— `read_actions = ["list", "retrieve"]` and
`write_actions = ["create", "update", "partial_update", "patch", "destroy"]`.
Any custom `@action(detail=..., methods=[...])` falls through to `None`,
which causes `APIScopePermission.has_permission` to return False with
`"This action does not support Personal API Key access"`. Every personal
API key, OAuth token, and MCP call to that endpoint 403s — even though
the ViewSet has `scope_object` set.

Two ways to fix it on a ViewSet with custom actions:

- **Per-class action lists.** Add `scope_object_read_actions` and / or
  `scope_object_write_actions` on the ViewSet, listing the custom action
  method names. Best when the actions are stable and share the
  ViewSet's scope.

  ```python
  class EvaluationConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
      scope_object = "evaluation"
      scope_object_read_actions = ["list"]
      scope_object_write_actions = ["set_active_key"]
  ```

- **Per-action override.** Pass `required_scopes=[...]` to `@action(...)`.
  Best when the scope for one action diverges from the rest of the
  ViewSet (e.g. a write-shaped endpoint that's safe enough to expose
  with `:read`, like `EvaluationViewSet.test_hog`).

  ```python
  @action(detail=False, methods=["post"], required_scopes=["evaluation:read"])
  def test_hog(self, request, **kwargs): ...
  ```

When you add or rename a custom action, update one of the two — if you
forget, the new endpoint silently 403s every API-key caller. The default
test client uses `force_login` and skips the scope check, so unit tests
pass even when the production path is broken. Verify with a personal
API key (or via the MCP layer) before merging.

## See also

- [docs/ai-events-table-rollout.md](./docs/ai-events-table-rollout.md) — ongoing `ai_events` ClickHouse table rollout.
