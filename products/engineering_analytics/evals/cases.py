"""Real CI failures with a verified diagnosis, as eval fixtures.

Every case is a failure that actually happened in `PostHog/posthog` and whose root cause
was later confirmed — by the fix that merged, or by an engineer in the thread correcting a
first, wrong answer. `evidence` is what a triager sees before investigating: the failing
job, the error, and the surrounding context. Nothing downstream of the diagnosis is in it.

Two things the ground truth encodes that a plausible-sounding answer will miss:

`attribution` is the question people actually ask ("is this my fault?"), and the answer is
not always "not you" — `mcp_char_budget` is the author's own doing. A grader that only ever
rewards exoneration would score well on a bot that always says "master is broken".

`decoy` is the loudest wrong answer: the error text a shallow read lands on. `jest_jsdom`
fails visibly at a tooltip assertion whose cause is a ReferenceError several frames earlier,
and `self_hosted_runner_disconnect` prints a module-resolution error 52 times per job in
passing and failing jobs alike. Confusing symptom with cause is the failure mode this suite
exists to catch, so it is scored separately from whether the diagnosis reads well.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Who owns the failure. The eval asks for exactly one, because a triage answer that hedges
# across two is not actionable.
Attribution = Literal[
    "pr_caused",  # the PR under discussion introduced it
    "trunk_broken",  # master is red; every concurrent PR sees it
    "flaky",  # same commit both passes and fails
    "infrastructure",  # runner, network, or registry — not the repo's code
]


@dataclass(frozen=True, kw_only=True)
class CIDiagnosisCase:
    """One CI failure and the diagnosis a good triager should reach."""

    name: str
    evidence: str
    attribution: Attribution
    root_cause: str
    """The mechanism, in one or two sentences. Judged semantically, not by string match."""
    decoy: list[str] = field(default_factory=list)
    """Substrings that name the symptom rather than the cause. Present in the root cause of a
    shallow answer, absent from a correct one."""
    source: str = ""


CASES: list[CIDiagnosisCase] = [
    CIDiagnosisCase(
        name="chdb_mock_target_moved",
        attribution="trunk_broken",
        evidence="""Two warehouse tests are failing across several different open PRs, and re-running does not clear them:

```
@posthog/products-data-warehouse:backend:test: FAILED backend/models/test/test_table.py::TestTable::test_chdb_introspection_escapes_single_quotes_in_placeholders_0_get_columns - Exception: Could not get columns
@posthog/products-data-warehouse:backend:test: FAILED backend/models/test/test_table.py::TestTable::test_chdb_introspection_escapes_single_quotes_in_placeholders_1_get_count - Exception: Could not get columns
```

The test patches `chdb.query`. The production code in `products/warehouse_sources/backend/models/table.py` calls `run_chdb_query()`, which shells out to chdb in a subprocess via `subprocess.run` and returns `process.stdout`. Two engineers report the same two tests blocking unrelated PRs.""",
        root_cause=(
            "The test mocks `chdb.query`, but the code under test was refactored to call "
            "`run_chdb_query()`, which runs chdb in a subprocess. The patch never intercepts the "
            "real call, so the subprocess runs for real, fails to reach storage, and the code "
            "falls through to its ClickHouse path."
        ),
        decoy=["could not get columns", "clickhouse is down", "s3 is flaky"],
        source="#flakey-tests 2026-07-07; fix merged as PostHog/posthog#68855",
    ),
    CIDiagnosisCase(
        name="jest_jsdom_performance_now",
        attribution="flaky",
        evidence="""`packages/quill/packages/charts/src/charts/PieChart/PieChart.test.tsx` fails intermittently in Frontend CI. The reported failure:

```
● PieChart › hover & tooltip › switches the tooltip to the other slice when the cursor moves

    tooltip not yet rendered

    <body>
      <div>
        <div style="...">Something went wrong rendering this chart</div>
      </div>
    </body>

      at waitForTooltip (../packages/quill/packages/charts/src/testing/tooltip.ts:92:23)
```

Earlier in the same job's console output:

```
Error: Uncaught [ReferenceError: performance is not defined]
    at tick (/home/runner/.../src/core/hooks/useHoverAnimation.ts:...)
```

`useHoverAnimation` drives the hover fade-in and calls `performance.now()` on mouse move. The test helper `setupSyncRaf()` mocks `requestAnimationFrame` to run synchronously. The chart is wrapped in an error boundary that renders "Something went wrong rendering this chart".""",
        root_cause=(
            "`useHoverAnimation` calls `performance.now()`, which is not always defined in the "
            "jsdom environment. The ReferenceError is caught by the chart's error boundary, so the "
            "chart never renders and no tooltip ever appears. The tooltip assertion is the "
            "downstream symptom; `setupSyncRaf()` mocks rAF but does not guarantee `performance`."
        ),
        decoy=["tooltip not yet rendered", "tooltip timing", "waitfor timeout", "animation timing"],
        source="#flakey-tests 2026-06-25; fix merged as PostHog/posthog#65972",
    ),
    CIDiagnosisCase(
        name="mcp_char_budget",
        attribution="pr_caused",
        evidence="""A PR adding alerts MCP tools (`products/alerts/mcp/tools.yaml`, `services/mcp/src/tools/generated/alerts.ts`) has a failing MCP CI job. The author says it is unrelated to their changes.

```
tests/unit/execute-sql-description.test.ts > formatExecuteSqlDescription > keeps data-catalog discovery within its character budget

AssertionError: expected 1444 to be less than 1200
```

The job log also prints:

```
MCP unit test artifacts are out of date. Run 'pnpm --filter=@posthog/mcp run test -u' and commit the result.
```

The same job is green on master.""",
        root_cause=(
            "The PR's new alerts MCP tools expand the data catalog that feeds the execute-sql "
            "description, pushing it from under the asserted 1200-character budget to 1444. The "
            "budget assertion is doing its job. Master is green because master lacks these tools."
        ),
        decoy=["out of date", "snapshot", "artifacts", "unrelated", "master is broken", "flaky"],
        source="#flakey-tests 2026-07-17, PostHog/posthog#71705",
    ),
    CIDiagnosisCase(
        name="receivers_baseline_not_updated",
        attribution="trunk_broken",
        evidence="""`test_setup_receivers_match_baseline` is failing in Django Core shard 19/19. The failure names three signal receivers that are registered at runtime but absent from the baseline file:

```
post_delete:products.ai_observability.backend.models.llm_prompt.invalidate_llm_prompt_label_cache
post_save:products.ai_observability.backend.models.llm_prompt.invalidate_llm_prompt_label_cache
post_save:products.early_access_features.backend.signals.create_waitlist_survey_on_concept_stage
```

The same shard is failing on every recent master commit. Re-running the job on the PR does not help. The PR under discussion touches MCP tool definitions only.""",
        root_cause=(
            "New Django signal receivers were merged to master without regenerating the checked-in "
            "receivers baseline, so the baseline-comparison test fails for everyone. It needs a "
            "baseline regeneration committed to master (`UPDATE_SETUP_RECEIVERS_BASELINE=1`); "
            "re-running a PR cannot fix it."
        ),
        decoy=["flaky", "shard", "sharding", "rerun", "your pr"],
        source="#flakey-tests 2026-07-17, PostHog/posthog#71705 thread",
    ),
    CIDiagnosisCase(
        name="mcp_property_definition_post",
        attribution="flaky",
        evidence="""The MCP CI integration job failed and passed on re-run 32 times in the last 7 days, always on the same test.

`services/mcp/tests/tools/projects.integration.test.ts` has a `beforeAll` for the `property-definition-update tool` block that looks for the `$browser` property definition and, when it is missing, tries to create it with `POST /api/projects/{id}/property_definitions/`.

`PropertyDefinitionViewSet` in `posthog/taxonomy/property_definition_api.py` composes List/Retrieve/Update/Destroy and has no `CreateModelMixin`. The failed attempt is annotated `This action does not support personal API key access`.

The CI workflow pre-seeds `EventDefinition` rows for `$pageview`, `$pageleave`, `$autocapture` and `$screen`, but seeds no `PropertyDefinition` rows. `vitest.integration.config.mts` sets `retry: 1`.""",
        root_cause=(
            "The test's `beforeAll` depends on whether generated demo data happened to produce a "
            "`$browser` property definition that run. Its fallback POST can never succeed because "
            "the viewset has no create action, and `retry: 1` does not help because a throwing "
            "`beforeAll` is not retried. Nothing seeds `PropertyDefinition` rows, so the "
            "precondition is left to chance."
        ),
        decoy=["403", "permissions", "api key scope", "auth"],
        source="Signals report 2026-08-03, PostHog/posthog#76476",
    ),
    CIDiagnosisCase(
        name="self_hosted_runner_disconnect",
        attribution="infrastructure",
        evidence="""Jobs on self-hosted runners are failing. The logs contain a long parade of module-resolution warnings around dynamic imports in a `codeowners.ts` script:

```
ERR_MODULE_NOT_FOUND  Cannot find module '.../codeowners.ts'
```

Counting occurrences across the window: the warning appears exactly 52 times per job, in passing jobs and failing jobs alike. In the source, those imports sit inside a try/catch and the handler calls `console.log`.

Every failed job in the window carries the annotation:

```
The self-hosted runner lost communication with the server. Verify the machine is running and has a healthy network connection.
```

The failing jobs ran for 15 to 20 minutes before disconnecting. Passing jobs on the same runners completed normally.""",
        root_cause=(
            "The self-hosted runners lose communication with GitHub mid-job, which fails the job. "
            "The module-resolution warnings are caught and logged, appear identically in passing "
            "jobs, and do not affect exit status — they are noise, not the cause."
        ),
        decoy=["err_module_not_found", "module not found", "dynamic import", "codeowners", "import path"],
        source="Mendral published post-mortem, 'How do we know if our agent is right?'",
    ),
]
