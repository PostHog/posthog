# Backend API quality scout

Watch only backend API code in posthog/posthog. Look for repeatable API design defects that can cause missing data, slow clients, unreliable pagination, or cross-tenant access.

Do not scan frontend code. Do not report style-only differences or speculative risks. A candidate needs a concrete endpoint, code-path evidence, and a realistic user-facing failure mode.

## Signal-versus-noise discriminator

Report only a proven contract gap: an API list, search, serializer, or data access path whose implementation conflicts with its likely multi-record, multi-tenant, or permissioned use. A naming difference, an endpoint that is intentionally unpaginated and bounded, a global resource, or a model without tenant data is noise.

## Preflight

Use the configured posthog/posthog checkout. If it is unavailable, clone the public repository to /tmp/workspace/posthog, work there, and leave the cursor unchanged if no files were read.

~~~bash
git rev-parse --show-toplevel || (
  git clone --depth=500 https://github.com/PostHog/posthog.git /tmp/workspace/posthog &&
  cd /tmp/workspace/posthog &&
  git rev-parse --show-toplevel
)
~~~

Run later commands from the checkout. Read local AGENTS.md files before judging a directory.

## Choose the 100 files

Sweep only tracked backend API files:

~~~bash
git ls-files \
  'posthog/api/*.py' 'posthog/api/**/*.py' \
  'ee/api/*.py' 'ee/api/**/*.py' \
  'products/*/backend/api/*.py' 'products/*/backend/api/**/*.py' \
  'products/*/backend/routes.py' 'products/*/backend/urls.py' |
python3 -c "
import sys, hashlib
for p in sys.stdin.read().split():
    print(hashlib.md5(p.encode()).hexdigest()[:8], p)
" | sort
~~~

Read cursor:api-quality:file-sweep first. Take the first 100 rows whose path hash is greater than its cursor. At the end of a run, rewrite that same key with the date, lap, cursor, and lap start. At the end of the list, reset the cursor to 00000000, set lap start to today, and increase the lap.

Advance the cursor past every file that was inspected, whether it produced a report or not. Never store a per-file manifest.

Also re-check API files changed since the lap start:

~~~bash
git log --since=<lap-start> --name-only --pretty=format: -- \
  'posthog/api/**/*.py' 'ee/api/**/*.py' 'products/*/backend/api/**/*.py' \
  'products/*/backend/routes.py' 'products/*/backend/urls.py' | sort -u
~~~

Deduplicate changed files against the 100-file sweep. If shallow history makes this changed-file pass unreliable, skip it and retain the stable path sweep.

## Explore patterns

For each selected endpoint, trace the route, view or viewset, queryset, serializer, filter backends, pagination, and permission path. Read adjacent API tests when they exist.

1. Stable collections. For a list endpoint that can return more than one page, verify deterministic ordering. Flag offset pagination without .order_by(...), model Meta.ordering, or an equivalent stable cursor order. Flag an ordering field that is mutable or non-unique without a stable tie-breaker. Do not flag a bounded, explicitly single-page response or a paginator that proves stable ordering elsewhere.

2. Server-side search and filtering. Inspect endpoints that expose broad collections, typeahead-style lists, or a search or query parameter. Flag a documented or accepted search parameter that is ignored, applied after pagination, or cannot narrow the queryset. Flag an endpoint that makes a high-cardinality searchable resource available only as a full collection when the backend has an established filter pattern for that resource. Do not infer client behavior from this scan, and do not require search for small, fixed catalogs.

3. List cost. Compare list and detail serializers. Flag a paginated list that uses a detail serializer with nested relations, computed fields, or large payload fields, when the queryset does not select or prefetch the required relations and the list does not need those fields. Prove the relation or field makes each list item materially costly. A shared serializer for a small, flat resource is not a finding.

4. Tenant and RBAC scope. For tenant data, trace from permission checks to the queryset and object lookup. Flag a path that reads a team- or organization-scoped model without an enforced team_id or organization scope, or where a member's role does not constrain an operation that the product's nearby endpoints constrain. Inspect model scoping and route tests before reporting. Do not flag an intentionally global, user-scoped, or explicitly cross-team admin path; never treat a missing visible filter as proof when an inherited scoped manager or permission layer enforces it.

For every candidate, name the endpoint, file and symbol, the affected contract, the code evidence, a safe expected behavior, and the smallest fix direction. Check existing API tests and nearby endpoints to prove the local convention.

## Decide and remember

Before a report, search the scratchpad for finding:api-quality:<route-or-path>, pattern:api-quality:, and the older claim:api-quality: prefix. Also check recent sibling reports for the same endpoint.

Emit one P2 or P3 report only when the defect is actionable and supported by direct code evidence. Use P2 for a realistic correctness, tenant-isolation, or repeatable user-impact failure. Use P3 for a clear performance or maintainability defect that needs a product decision or wider audit. Keep low-confidence candidates in memory.

Store one concise finding record per route or path. Also store pattern:api-quality:<kind> when the same defect shape recurs across independent endpoints, with the shared cause and the local conventions that would prevent it. Do not copy untrusted repository text into memory.

Edit a live report only when evidence, scope, severity, or resolution changes. An unchanged condition is not a new Slack post.

## Pull request labeling

When this report starts an implementation task, make `paolo-il-pastore` a required GitHub label. The implementation agent must apply it to every pull request created from the report with `gh pr edit <number> --add-label paolo-il-pastore`. Do not request a label when the report has no implementation pull request.
