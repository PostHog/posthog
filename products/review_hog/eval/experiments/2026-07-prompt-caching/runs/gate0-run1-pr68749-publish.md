# Reviewer-quality run — `gate0-run1-pr68749-publish`

- **Dumped:** 2026-07-06T20:48:45+00:00
- **Report id:** `019f3911-7629-7348-8448-d1aae91644c5` · **PR:** https://github.com/PostHog/posthog/pull/68749
- **Head:** `b4764b4a9a6f355ed1f230f15ebfd43e3a5c5133` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1880s (31.3 min)

## Config snapshot

- runtime / model / effort: `claude` / `claude-sonnet-5` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 1      | 4            | 8          | 8           | 4                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model                     | stage      | gens    | fresh in    | cache write | cache read     | output      | >200K gens | true $    | gw $      |
| ------------------------- | ---------- | ------- | ----------- | ----------- | -------------- | ----------- | ---------- | --------- | --------- |
| claude-sonnet-5           | review     | 82      | 119,275     | 606,051     | 9,845,464      | 72,902      | 0          | $4.45     | $4.45     |
| claude-opus-4-8           | validation | 31      | 31,232      | 216,688     | 3,225,156      | 37,195      | 0          | $4.05     | $4.05     |
| claude-sonnet-5           | blind-spot | 27      | 35,868      | 151,854     | 3,349,695      | 22,007      | 0          | $1.34     | $1.34     |
| claude-sonnet-5           | dedup      | 1       | 6,804       | 0           | 0              | 4,288       | 0          | $0.06     | $0.06     |
| claude-haiku-4-5-20251001 | other      | 1       | 471         | 0           | 0              | 6           | 0          | $0.00     | $0.00     |
| **total**                 |            | **142** | **193,650** | **974,593** | **16,420,315** | **136,398** | **0**      | **$9.90** | **$9.90** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = +0.0%.
- naive method (all prompt tokens at input price): $47.52 — 4.8× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $7.9812 over 142 gen(s) (true $7.9812, Δ -0.0%)
  - · of which cache read: $4.2516 over 134 gen(s) (true $4.2516, Δ +0.0%)
  - · of which cache write: $3.2491 over 140 gen(s) (true $3.2491, Δ +0.0%)
  - · of which fresh (derived): $0.4805 over 142 gen(s) (true $0.4805, Δ -0.0%)
  - output: $1.9219 over 142 gen(s) (true $1.9219, Δ +0.0%)

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | stage      | first gen | t1 cache read | t1 cache write |
| --------- | ---------- | --------- | ------------- | -------------- |
| …e23f6862 | review     | 20:15:18  | 0             | 73,218         |
| …5dbd75a0 | review     | 20:15:19  | 27,618        | 45,603         |
| …45201835 | review     | 20:15:37  | 27,618        | 45,602         |
| …ce6cdd06 | blind-spot | 20:27:59  | 0             | 76,265         |
| …423f769b | validation | 20:34:34  | 0             | 38,613         |

- units with turn-1 cache_read > 0: **2/5** (report the distribution, not a median).

## Chunking

- **chunk 1** (11 files): products/customer_analytics/backend/presentation/views/serializers.py, products/customer_analytics/backend/presentation/views/views.py, products/customer_analytics/backend/routes.py, products/customer_analytics/frontend/components/Accounts/AGENTS.md, products/customer_analytics/frontend/components/Accounts/AccountNotebooksExpansion.tsx, products/customer_analytics/frontend/components/Accounts/AccountRelationshipsExpansion.tsx, products/customer_analytics/frontend/components/Accounts/accountRelationshipsLogic.ts, products/customer_analytics/frontend/components/Accounts/accountsExpansionLogic.ts, products/customer_analytics/frontend/generated/api.schemas.ts, products/customer_analytics/frontend/generated/api.ts, services/mcp/src/api/generated.ts

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 3          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 1000 | 1     | review-hog-blind-spots-general                 | 2          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] consider · best_practice — products/customer_analytics/frontend/components/Accounts/AccountRelationshipsExpansion.tsx:13-68

**History tab row order doesn't read as a chronological timeline**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The PR and AGENTS.md describe this tab as showing 'the full assignment timeline', and the table exposes 'Started'/'Ended' columns that invite a chronological reading, with no sorter on either column. The data backing it (`list_account_relationships`, ordered `definition__name, -started_at`) is grouped by relationship-definition name first and only ordered by recency within that group. For an account with more than one relationship type, a user scanning the tab top-to-bottom for 'what changed most recently' will see rows interleaved by alphabetical definition name rather than by time, which doesn't match the 'timeline' framing.
- **Suggestion:** Either sort rows by `started_at` descending in the table (or add a `sorter` to the Started/Ended columns) so the tab reads as a true chronological timeline across all relationship types, or if grouping by relationship type is intentional, consider grouping visually (e.g. sub-headers per definition) so the order isn't mistaken for chronological.
- **Validator:** This is a presentation/taste concern, not a correctness bug. I confirmed the backend orders relationships by `definition__name, -started_at` (facade/api.py:1785) and the frontend renders them in that order with no sorter. But the displayed data is entirely correct — every row's Started/Ended/assignee values are right; only the row grouping is at issue. Grouping an account's assignments by relationship type (recency within each) is a reasonable, likely intentional layout, reinforced by 'Relationship' being the first column. The 'timeline' framing exists only in the PR body and AGENTS.md, not in user-facing copy — the tab is labeled 'Relationships,' so no user is promised a strictly chronological view. The predicted confusion is speculative, and the suggested fixes (add column sorters, re-sort by started_at, or add per-definition sub-headers) are optional UX enhancements rather than a fix for a real defect. Under the validation bar (precision over recall, drop style/taste and speculative UX when unsure), this should be dropped.

### [❌ dismissed] consider · performance — products/customer_analytics/frontend/components/Accounts/AccountNotebooksExpansion.tsx:139-139

**Relationships tab adds a 6th eager network fetch on every row expansion, regardless of active tab**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `useMountedLogic(accountRelationshipsLogic({ accountId }))` fires `loadRelationships` (via `afterMount`) the instant a row expands, even if the user never opens the Relationships tab — it's needed unconditionally because the always-visible sidebar (`ActiveRelationships`) reads from the same logic. This is consistent with the existing eager-fetch-all-tabs design documented in AGENTS.md, but it adds a sixth simultaneous request per row expansion (on top of notes, related-users, usage, spend, opportunities), all fired in parallel the moment any row is expanded. For a user who expands several account rows in quick succession (e.g. scanning the list), this compounds the number of concurrent backend calls with data most of them will never look at.
- **Suggestion:** If this becomes a real cost once traffic increases, consider deferring `accountRelationshipsLogic`'s fetch until either the sidebar needs it or the Relationships tab is actually opened, rather than eagerly mounting all six per-tab logics on every expand. Not blocking given it matches the existing architecture, but worth tracking as the number of eagerly-fetched tabs keeps growing.
- **Validator:** Speculative future-scale performance concern that the reviewer themselves marks as non-blocking and 'worth tracking if traffic increases' — the drop bar for speculative 'what if' issues. Investigation shows the fetch is not even wasteful in the common case: accountRelationshipsLogic fetches on afterMount (accountRelationshipsLogic.ts:49-51), and its data backs the ALWAYS-rendered sidebar summary ActiveRelationships (AccountNotebooksExpansion.tsx:218), not just the Relationships tab. So the request is genuinely required the moment a row expands, regardless of active tab; even the empty-sidebar case needs it to know there's nothing to show. The suggested fix is self-contradictory — deferring 'until the sidebar needs it' means fetching immediately on expand anyway. This is one bounded, user-initiated GET per expansion, consistent with the deliberate, AGENTS.md-documented eager-fetch-all-tabs design, not an N+1, unbounded loop, or hot-path issue. No concrete consequence at realistic scale (a user manually expanding a handful of rows), so under precision-over-recall this should be dropped.

### [❌ dismissed] consider · code_quality — products/customer_analytics/backend/presentation/views/serializers.py:545-554,63-71

**New AccountAssignmentSerializer duplicates the existing inline `_ACCOUNT_ASSIGNMENT_SCHEMA` shape instead of reusing it**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This chunk introduces `AccountAssignmentSerializer` (id: int, email: str, `ref_name = "AccountAssignment"`) as the typed OpenAPI shape for a user assigned to an account relationship. But the file already has `_ACCOUNT_ASSIGNMENT_SCHEMA` (lines 63-71) — an untyped, hand-written JSON-schema dict with the identical shape (`{id: integer, email: string}`, both required) — which is inlined three times into `_ACCOUNT_PROPERTIES_SCHEMA` for the account `properties.csm` / `account_executive` / `account_owner` fields (used by `AccountPropertiesField` via `@extend_schema_field`). Since that schema is inlined rather than given a reusable `$ref` component, the generated frontend types now carry two independent representations of the exact same logical concept ("a user assigned to something"): `AccountApiProperties.csm` is typed as an anonymous inline object (`{ id: number; email: string } | null`, see `products/customer_analytics/frontend/generated/api.schemas.ts:152-155`), while the new `AccountRelationshipApi.user` is typed as the named `AccountAssignmentApi | null`. Any future change to the assignee shape (e.g. adding `first_name`) now has to be made in two places to stay consistent, and consumers (frontend, MCP) get two different generated types for what is conceptually one thing.
- **Suggestion:** Point `csm`/`account_executive`/`account_owner` at the new `AccountAssignmentSerializer`'s schema instead of the raw inline dict — e.g. replace `_ACCOUNT_ASSIGNMENT_SCHEMA` with a `$ref`-style reference to the `AccountAssignment` component (drf-spectacular supports referencing another serializer's component via `PolymorphicProxySerializer` or by building the properties schema off `AccountAssignmentSerializer().data` field metadata), so both surfaces resolve to the same generated `AccountAssignmentApi` type. If backward-compat with the pinned `AccountApiProperties` component name blocks a full `$ref` swap right now, at least leave a comment noting the two schemas must be kept in sync.
- **Validator:** The duplication is real but intentional and non-defective, so this is a speculative maintainability observation rather than a keep-worthy issue. The inline `_ACCOUNT_ASSIGNMENT_SCHEMA` (lines 63-71) is deliberately kept verbatim — the comment at lines 61-62 states it exists 'so the generated AccountApiProperties component is unchanged' from the pre-isolation serializer. Swapping it for a $ref to the new AccountAssignment component risks mutating that intentionally-pinned OpenAPI component, which the reviewer concedes ('If backward-compat with the pinned AccountApiProperties component name blocks a full $ref swap...'). The two shapes are also not clearly one concept: properties.csm/account_executive/account_owner are account role assignments, while the new AccountAssignment is a user assigned to an account relationship (a separate feature); they coincide at {id, email} today but are semantically independent, so keeping them decoupled is defensible rather than wrong. Both generated types are correct right now — nothing is broken, no contract break, no user impact. The justification is speculative future maintenance ('e.g. adding first_name'), and the suggestion is an extract-and-reuse/DRY refactor plus a sync comment that largely duplicates the existing explanatory comment. This falls on the overengineering/style side and is already-handled/intentional, so under precision-over-recall it should be dropped.

### [✅ VALID] should_fix · best_practice — products/customer_analytics/backend/presentation/views/views.py:1039-1042

**AccountRelationshipViewSet missing class-level @extend_schema tag/path-param declaration used by every sibling nested account viewset**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** Every other viewset nested under `project_accounts_router` in this same file declares a class-level `@extend_schema(tags=["customer_analytics"], parameters=[OpenApiParameter(name="account_id", type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, description="UUID of the parent account.")])` immediately above the class: `AccountNotebookViewSet` (lines 782-792) and `CustomPropertyValueViewSet` (lines 977-986). `AccountRelationshipViewSet` (line 1039) has no such decorator, so the generated OpenAPI schema for this new `/accounts/{account_id}/relationships/` endpoint will be missing the `customer_analytics` tag grouping and the explicit UUID type/description for the `account_id` path parameter that its siblings carry. The file's own comment at line 58-61 explains why this matters here specifically: these facade-backed viewsets have no `queryset` for drf-spectacular to introspect, so path parameter type/description must be declared explicitly "to keep the generated OpenAPI (and MCP) path params byte-identical" — meaning this gap also propagates into the auto-generated MCP tool schema for this operation, not just the Swagger docs.
- **Suggestion:** Add the same class-level decorator used by `AccountNotebookViewSet`/`CustomPropertyValueViewSet` above `AccountRelationshipViewSet`:

```python
@extend_schema(
    tags=["customer_analytics"],
    parameters=[
        OpenApiParameter(
            name="account_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the parent account.",
        ),
    ],
)
class AccountRelationshipViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    ...
```

This keeps the generated OpenAPI/MCP schema for this endpoint consistent with its sibling nested viewsets.

- **Validator:** Confirmed, concrete, and directly introduced by this PR. Both sibling nested viewsets under project_accounts_router — AccountNotebookViewSet (lines 782-792) and CustomPropertyValueViewSet (lines 977-986) — carry a class-level @extend_schema declaring tags=["customer_analytics"] and the account_id UUID PATH parameter with description. The new AccountRelationshipViewSet (line 1039) has only a method-level @extend_schema on list (include_history + responses) and omits the class-level decorator. The file's own comment (lines 59-62) documents why this matters: these facade-backed viewsets have no queryset for drf-spectacular to introspect, so the path param type/description must be declared explicitly 'to keep the generated OpenAPI (and MCP) path params byte-identical.' The result is a real, verifiable divergence — the generated schema for /accounts/{account_id}/relationships/ will lack the customer_analytics tag grouping and will type account_id as a generic string without a description, unlike every sibling endpoint. This flows into both the OpenAPI docs and the auto-generated MCP tool schema, which CLAUDE.md explicitly calls out as things schema annotations must feed. This is not style or speculation: named trigger, named consequence, trivial low-risk fix matching an established in-file pattern. Impact is metadata-only (no runtime/security/data effect, since access control is enforced in code), but given the project's documented emphasis on generated-schema and MCP consistency, should_fix is appropriate.

### [✅ VALID] should_fix (validator→consider) · bug — products/customer_analytics/frontend/components/Accounts/AccountNotebooksExpansion.tsx:59-84

**Sidebar cannot distinguish 'no relationships assigned' from 'failed to load'**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** ActiveRelationships renders null whenever activeRelationships.length === 0, which is true both when the account genuinely has no active assignments and when accountRelationshipsLogic.loadRelationships failed (relationships stays null, so (relationships ?? []).filter(...) is also []). The sibling AccountRelationshipsExpansion tab explicitly differentiates these two cases via `relationships === null ? 'Failed to load relationships.' : 'No assignments on this account yet.'`, but the sidebar summary — which is the more prominent, at-a-glance surface for 'who is the CSM/AE on this account' — silently disappears in both cases. accountRelationshipsLogic's loadRelationshipsFailure listener deliberately skips a toast ('No toast: relationships === null renders the table's failure empty state'), which is true for the tab but not for the sidebar, so a transient fetch failure can make a rep believe an account has no assigned owner when the data simply didn't load.
- **Suggestion:** Have ActiveRelationships also read `relationships` (not just `activeRelationships`) and render a distinct state when `relationships === null` post-load (e.g. a small inline error note or icon), instead of silently rendering nothing indistinguishably from the true-empty case.
- **Validator:** The premise checks out: accountRelationshipsLogic initializes `relationships` to null and derives `activeRelationships` as `(relationships ?? []).filter(...)`, so it is `[]` both on a genuinely-empty account and on a failed load (relationships stays null). ActiveRelationships returns null whenever `activeRelationships.length === 0`, so the sidebar silently vanishes in both cases, while the sibling tab explicitly distinguishes them via `relationships === null ? 'Failed to load relationships.' : 'No assignments on this account yet.'` and the loadRelationshipsFailure listener deliberately skips a toast on the assumption the table empty-state covers it — which the sidebar does not do. That is a real swallowed-failure/ambiguous-state defect a transient fetch error will actually hit, so it clears the keep bar. But the severity is overstated: the relationships sidebar is a distinct new read-only concept, not the CSM/AE/owner roles (those are separate table columns/MemberSelect and are unaffected), so the 'rep thinks the account has no owner' framing is inflated. The failure is also captured via captureException and is surfaced in the Relationships tab (same shared fetch), so it is not fully invisible. Given the error is still reachable in the tab, the exception is reported, and this is a new supplementary read-only feature, this is a genuine but minor issue — keep it on record at `consider` rather than should_fix.

### [✅ VALID] should_fix (validator→consider) · bug — products/customer_analytics/frontend/components/Accounts/AccountNotebooksExpansion.tsx:67-81

**Active-relationships sidebar doesn't group concurrent assignees of the same non-single-holder relationship**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** ActiveRelationships maps activeRelationships one row per assignment and renders `<LemonLabel>{relationship.definition.name}</LemonLabel>` for every row. AccountRelationshipDefinition.is_single_holder is a real, tested feature (see backend/test/test_relationships.py::test_multi_holder_allows_concurrent_assignees) that allows multiple concurrently-active users for the same relationship (e.g. a 'Field engineer' or 'Account team' role held by two people at once). For such a definition, the sidebar renders the same relationship-name label twice in a row (once per assignee) instead of one label with both assignees listed underneath, which reads as a rendering glitch/duplicate rather than 'two people hold this role'.
- **Suggestion:** Group activeRelationships by `definition.id` before rendering, so each distinct relationship type gets a single label with all of its active assignees listed beneath it (e.g. `groupBy(activeRelationships, r => r.definition.id)` then map over the groups).
- **Validator:** The premise is verified against the codebase: is_single_holder is a real model field (relationship.py:21, default True) and test_multi_holder_allows_concurrent_assignees confirms is_single_holder=False allows multiple concurrent active assignees for one definition. ActiveRelationships renders one <LemonLabel>{definition.name}</LemonLabel> per assignment, so a multi-holder definition with two active holders shows the same label twice consecutively instead of one label with both assignees beneath — which reads as a duplicate/glitch, and groupBy(definition.id) is the obviously-intended fix. This is a genuine presentation defect for a supported feature, not pure taste. Severity is capped, though, for two reasons: the displayed data is fully correct (both assignees appear — it is cosmetic grouping, not wrong/missing data), and the concurrent-assignee scenario is not currently reachable by users. is_single_holder defaults to True, and this PR is read-only: only the list endpoint is exposed (routes.py:76-78), the assign/end write path is explicitly deferred to a later stacked PR, and the only production source of assignments today is sync_from_account_properties, which creates single-holder role rows. Multi-holder concurrent assignments only become reachable once the write path ships. So this is a real latent polish issue worth keeping on record, but not an actionable blocker in this PR — should_fix overstates it, consider is proportionate.

### [✅ VALID] should_fix (validator→consider) · performance — products/customer_analytics/backend/presentation/views/views.py:1039-1070

**Account relationships history endpoint has no server-side pagination or row cap**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** AccountRelationshipViewSet sets `pagination_class = None` and its `list()` returns whatever `api.list_account_relationships(...)` yields with no limit. The frontend (`accountRelationshipsLogic.ts`) always calls this endpoint with `include_history=true` — the only mode actually exercised in production — so every request returns the account's entire relationship-assignment history in one unbounded response. Once the write path (assign/end) ships, each reassignment adds a permanent row, so this grows without bound over an account's lifetime with nothing capping it server-side. This is inconsistent with sibling list endpoints in the very same file: `AccountNotesViewSet` and `CustomerProfileConfigViewSet` both go through the existing `_paginate_via_facade` helper (limit/offset), which this new endpoint bypasses entirely even though the PR describes this tab as 'paginated' — in reality pagination only happens client-side over an already-fully-fetched array (see `AccountRelationshipsExpansion.tsx`), so the wire payload itself has no ceiling.
- **Suggestion:** Reuse the existing `_paginate_via_facade` pattern (as `AccountNotesViewSet` does) to add real offset/limit pagination for the `include_history=true` case, or at minimum cap the underlying queryset (e.g. `.order_by(...)[:500]`) as a defensive limit so a single account's history can't return an unbounded result set.
- **Validator:** The premise is accurate: AccountRelationshipViewSet sets pagination_class = None and list() returns api.list_account_relationships(...) unbounded, and the frontend always sends include_history=true, so each request returns the account's full assignment history with no server-side cap that will grow permanently once the deferred write path ships. That is a real reliability kernel, more than pure noise. But several findings cap its severity to below should_fix. First, the 'inconsistent with siblings' framing is overstated — CustomPropertyValueViewSet (line 991/1006) uses the identical pagination_class = None + full-list pattern, so unbounded is an existing precedent for bounded-cardinality per-account sub-resources. Second, the unbounded single fetch is intentional: per the PR and CLAUDE.md, one fetch feeds both the sidebar activeRelationships summary (which needs the entire active set) and the client-paginated history tab, so the reviewer's primary fix (server-side \_paginate_via_facade) would actually break the sidebar summary by computing 'active' from a partial page — only the secondary defensive-cap suggestion is design-compatible. Third, realistic scale is modest: relationship assignments are human-driven role changes (CSM/AE/owner churn), not event-scale data, so even years of churn yields a few hundred small rows — a trivial payload that does not bite at realistic scale — and the growth-driving write path is deferred to a later PR. So this is a sensible future hardening (a defensive queryset cap), not an actionable blocker now. Keep it on record at consider rather than should_fix.

### [❌ dismissed] consider · best_practice — products/customer_analytics/frontend/components/Accounts/AccountNotebooksExpansion.tsx:59-84

**ActiveRelationships sidebar has no loading state, unlike its sibling UsefulLinks widget in the same file**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** `ActiveRelationships` (added by this PR) reads only `activeRelationships` from `accountRelationshipsLogic` and returns `null` whenever the list is empty — which is also true before the fetch resolves, since `relationships` starts as `null` and the `activeRelationships` selector maps that to `[]`. The logic already exposes `relationshipsLoading` (used by the sibling tab component, `AccountRelationshipsExpansion.tsx:14,60`), but `ActiveRelationships` never reads it. Contrast this with `UsefulLinks`, defined right above it in the same file (lines 86-124): it explicitly branches on `accountLoading` to render three `LemonSkeleton` placeholders while data is in flight, then swaps to the real content. Because `ActiveRelationships` sits directly beside `UsefulLinks` in the sidebar (`<div className="w-fit shrink-0 flex flex-col gap-4">`), a user expanding a row now sees the Useful-links skeleton animate in immediately while the Relationships section stays entirely blank and then pops in abruptly once the fetch completes — an inconsistent, jarring loading experience between two adjacent widgets added/touched in the same component.
- **Suggestion:** Thread `relationshipsLoading` into `ActiveRelationships` and render skeleton placeholders (mirroring `UsefulLinks`'s pattern) while the initial fetch is in flight, only falling through to the `null`-when-empty behavior once loading has completed.
- **Validator:** The premise checks out — UsefulLinks (lines 86-124) shows LemonSkeleton placeholders while accountLoading, whereas ActiveRelationships (59-84) reads only activeRelationships, returns null while empty (including during the in-flight fetch, since relationships starts null and the selector maps it to []), and never uses the available relationshipsLoading. But this is a pure loading-experience/UI-consistency polish with no behavioral difference: the data is correct, nothing breaks, and the section renders fine once loaded — the only delta is a brief blank-then-pop-in versus a skeleton during a quick GET. No correctness, data, security, performance, or reliability impact, which is the drop bar for style/taste. It is also not an unambiguous improvement: ActiveRelationships is intentionally hidden when empty (per the area's design), and relationships are a brand-new opt-in feature so most accounts have none — a naive loading skeleton would flash and then disappear for that common empty case, arguably worse UX. Under precision-over-recall this is a cosmetic nitpick to drop; the reviewer already scored it the lowest priority (consider).
