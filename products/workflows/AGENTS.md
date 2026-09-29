# Workflows development guide

Workflows is on the way to an isolated product: other code reaches it only through a public surface, so a workflows-only change can skip the full backend suite.
Read [`CONTRIBUTING.md`](./CONTRIBUTING.md) when you add a trigger type, an action node, or a Hog function template.

## The boundary

- Code outside `products/workflows/` imports only `backend/facade/`, `backend/presentation/views/`, and `backend/routes.py`. Tests count too. `hogli lint:tach` fails any other import.
- When outside code needs something new from workflows, add a function to `backend/facade/api.py`. It takes ids and returns a frozen type from `backend/facade/contracts.py`, never a model or a QuerySet. `hogli product:lint workflows` checks the facade signatures.
- A test outside this product that needs a workflow row uses a helper in `backend/facade/testing.py`. Do not reach for `HogFlow` or `apps.get_model`.
- Never widen the boundary to make an import pass: no workflows internals in a tach `expose` list or a legacy-leak block, and no new workflows entries in the `ignore_imports` lists in `pyproject.toml`. No check catches these edits, so review is the only control.
- The views in `backend/presentation/views/` reach only the facade. The existing `ignore_imports` entries under "workflows presentation wave" are debt to delete, not a pattern to copy.

Read [`isolating-product-facade-contracts`](../../.agents/skills/isolating-product-facade-contracts/SKILL.md) when you change the facade, the contracts, or the presentation layer.
