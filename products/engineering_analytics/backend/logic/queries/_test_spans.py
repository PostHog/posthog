"""The one definition of the per-test CI span scan and what it proves (domain rules defined once, APOSD).

Backend CI emits one OTel span per test into the Traces store (span name = reconstructed
pytest nodeid, ``test.*`` attributes, ``ci.*`` resource attributes; see
``.github/scripts/report_test_timings.py``). Every query over that signal (the test-health
queue and the per-team rollups) embeds ``run_evidence()``, so the service fence, the signal
outcomes, the repository scoping, the ownership fallback, and above all the **grain** cannot
drift apart. Sharing a predicate string was not enough: each caller still counted its own way,
and they disagreed.

The grain is the CI run, not the span and not the run attempt:

- One run fans a test out across matrix legs (person-on-events, compat, and friends), so span-grain
  counting multiplies a single failure by the number of legs that ran it. At run grain a failure in
  any leg counts once, and outweighs a pass in another.
- Every attempt of a run tests the same commit, so attempts are repeated trials: a run that both
  failed and passed a test has proven it nondeterministic, whichever attempt failed first. That is
  what ``recovered_in_run`` means. Backend CI runs pytest without ``--reruns`` deliberately (failures
  stay visible instead of being retried away), so a "re-run failed jobs" recovery is where that proof
  comes from; ``rerun_passed`` is the same proof from the handful of tests hand-marked
  ``@pytest.mark.flaky(reruns=N)``.

The pairing key is wider than the run: two trials disagree iff they ran the same code state in the
same lane, so recovery proof pairs at (tree, lane).

- Tree: ``ci.sha`` is GITHUB_SHA, which on pull_request events is the refs/pull/N/merge commit, so
  equal ``ci.sha`` across two different runs means a byte-identical tree (a new run after master
  moves gets a new merge sha and correctly won't pair). A failure in run A recovered by a pass in
  run B at the same sha is the same same-commit proof a re-run attempt gives; the evidence still
  counts per run (run A is the recovered one, run B's unpaired passes are not evidence).
- Lane: the matrix leg (job config), read from the job-root span's ``shard.suite``/``shard.segment``
  through the shared trace_id. A pass in another leg runs a different config and proves nothing, so
  pairs never form across lanes. Spans whose lane can't be resolved (no in-window job-root span)
  share the '' lane, degrading to run/tree-grain pairing for those spans only.

The emitter only ships first-attempt passes above a duration threshold, so tree pairing sees part
of the passing corpus: a pairing pass is proof, its absence proves nothing (which is already how
all evidence here works). Failures with no recovery prove nothing about determinism. This surface
answers how much a failing test costs us, so unproven failures are ranked by blast radius and never
called flaky.
"""

from datetime import datetime

from posthog.hogql import ast

# Only test spans carry test.outcome (job-root and setup spans don't), and only these
# outcomes are flaky signal. Plain 'skipped' spans never reach any aggregation; 'passed'
# spans are read only from re-run attempts and from trees a run failed (the scan's two
# recovery arms), where they are the same-commit recovery proof.
SIGNAL_OUTCOMES = ["failed", "error", "rerun_passed", "xfailed"]

# Scope to the CI test-timing emitter (report_test_timings.py sets this as service.name);
# without it any team span carrying a test.outcome attribute would pollute.
CI_SERVICE_NAME = "ci-backend"

# Spans emitted before the owner stamp existed (or from paths with no owner) group here.
UNOWNED_TEAM = "unowned"


_RUN_EVIDENCE = """
    SELECT
        nodeid,
        run_id,
        argMax(owner_team, lane_at) AS owner_team,
        anyIf(selector, selector != '') AS selector,
        anyIf(pr_number, pr_number != '') AS pr_number,
        anyIf(branch, branch != '') AS branch,
        max(is_current) AS is_current,
        max(lane_failed) AS failed_in_run,
        max(lane_quarantined) AS quarantined_in_run,
        -- Proof of nondeterminism however it lands: an in-job retry recovered the test, another
        -- attempt of the run (same commit, same lane) disagreed with its failure, or another run
        -- testing the identical tree (same merge sha, same lane) passed it.
        max(lane_recovered OR (lane_failed AND tree_recovered)) AS recovered_in_run,
        -- Recovery passes are not signal, so recency comes from the signal trials alone.
        maxIf(lane_signal_at, lane_failed OR lane_rerun_passed OR lane_quarantined) AS run_signal_at
    FROM (
        -- Cross-run same-tree pairing: spread pass proof across every run of one (tree, lane).
        -- Unstamped spans (sha = '') never tree-pair. The window includes the lane's own runs,
        -- which adds nothing new: a run whose lane both failed and passed is already recovered.
        SELECT
            nodeid,
            run_id,
            owner_team,
            selector,
            pr_number,
            branch,
            is_current,
            lane_failed,
            lane_quarantined,
            lane_rerun_passed,
            lane_recovered,
            lane_at,
            lane_signal_at,
            sha != '' AND max(lane_passed OR lane_rerun_passed) OVER (PARTITION BY nodeid, sha, lane) AS tree_recovered
        FROM (
            -- One row per (test, run, lane): every attempt of a run re-tests the same commit in
            -- the same job config, so a lane's attempts are repeated trials and a lane that both
            -- failed and passed has proven the test nondeterministic. Scoping the pair to the
            -- lane keeps a pass in another matrix leg (a different config) from reading as
            -- recovery. Pass-only rows exist solely to donate tree proof; the outer HAVING keeps
            -- them from surfacing as evidence.
            SELECT
                nodeid,
                run_id,
                lane,
                any(sha) AS sha,
                argMax(owner_team, trial_at) AS owner_team,
                anyIf(selector, selector != '') AS selector,
                anyIf(pr_number, pr_number != '') AS pr_number,
                anyIf(branch, branch != '') AS branch,
                max(is_current) AS is_current,
                max(trial_failed) AS lane_failed,
                max(trial_rerun_passed) AS lane_rerun_passed,
                max(trial_quarantined) AS lane_quarantined,
                max(trial_passed) AS lane_passed,
                max(trial_rerun_passed) OR (max(trial_failed) AND max(trial_passed)) AS lane_recovered,
                max(trial_at) AS lane_at,
                maxIf(trial_at, trial_failed OR trial_rerun_passed OR trial_quarantined) AS lane_signal_at
            FROM (
                -- One row per (test, run attempt, lane). Older data re-reported shards an attempt
                -- never re-executed, and spans without a resolvable lane share the '' lane; within
                -- one trial a failure outweighs a pass, so re-reported or lane-less noise never
                -- reads as recovery.
                SELECT
                    nodeid,
                    run_id,
                    lane,
                    any(sha) AS sha,
                    argMax(owner_team, span_timestamp) AS owner_team,
                    anyIf(selector, selector != '') AS selector,
                    anyIf(pr_number, pr_number != '') AS pr_number,
                    anyIf(branch, branch != '') AS branch,
                    max(is_current) AS is_current,
                    max(outcome IN ('failed', 'error')) AS trial_failed,
                    max(outcome = 'rerun_passed') AS trial_rerun_passed,
                    max(outcome = 'xfailed') AS trial_quarantined,
                    max(outcome = 'passed') AND NOT trial_failed AS trial_passed,
                    max(span_timestamp) AS trial_at
                FROM (__SPAN_SCAN__)
                GROUP BY nodeid, run_id, lane, attempt
            )
            GROUP BY nodeid, run_id, lane
        )
    )
    GROUP BY nodeid, run_id
    -- The scan admits passes so they can pair with a failure above; unpaired they are not
    -- evidence, and a pass-only row would surface as an all-zero test everywhere downstream.
    HAVING failed_in_run OR recovered_in_run OR quarantined_in_run
"""


def run_evidence(*, bounded: bool) -> str:
    """One row per (test, CI run): what that run proves about that test.

    Every consumer groups this, never the raw spans, so all of them count at the same grain and
    agree on what the signal means. See the module docstring for why the run is the grain.

    ``bounded`` adds the upper time bound; some callers scan to now.
    """
    scan = _SCAN.replace("__LANES__", _LANES).replace("__FAILING_TREES__", _FAILING_TREES)
    scan = scan.replace("__DATE_TO__", " AND timestamp <= {date_to}" if bounded else "")
    return _RUN_EVIDENCE.replace("__SPAN_SCAN__", scan)


# Job-root spans carry the lane identity: shard.suite/shard.segment name the matrix leg, and a
# job's test spans share its trace_id. The shard group number is deliberately not part of the
# lane: sharding is duration-balanced and moves tests between shards across runs, while the leg
# is the actual job config. A test span whose root span is outside the scan window resolves to
# the '' lane, degrading that span to lane-less pairing rather than inventing a lane.
_LANES = """
    SELECT
        trace_id,
        concat(attributes['shard.suite'], ':', attributes['shard.segment']) AS lane
    FROM posthog.trace_spans
    WHERE service_name = {service_name}
        AND lower(resource_attributes['ci.repository']) = lower({repository})
        AND timestamp >= {scan_from}__DATE_TO__
        AND ifNull(attributes['shard.suite'], '') != ''
"""

# The (test, tree) pairs with a recorded failure: the only trees whose first-attempt passes are
# worth admitting, so the pass scan stays bounded by the failing set instead of reading the whole
# passing corpus. Failures only ('xfailed' is already masked and 'rerun_passed' is already proof),
# so the set stays as small as the signal itself.
_FAILING_TREES = """
    SELECT
        name,
        resource_attributes['ci.sha'] AS sha
    FROM posthog.trace_spans
    WHERE service_name = {service_name}
        AND lower(resource_attributes['ci.repository']) = lower({repository})
        AND timestamp >= {scan_from}__DATE_TO__
        AND attributes['test.outcome'] IN ('failed', 'error')
        AND ifNull(resource_attributes['ci.sha'], '') != ''
"""

# Scans [scan_from, date_to?]; `is_current` splits rows at {date_from} so a caller scanning
# an extra prior window (scan_from < date_from) gets the current/prior split for free. A
# caller without a prior window passes scan_from = date_from and ignores the column.
_SCAN = """
    SELECT
        name AS nodeid,
        attributes['test.selector'] AS selector,
        attributes['test.outcome'] AS outcome,
        coalesce(nullIf(attributes['test.owner_team'], ''), {unowned_team}) AS owner_team,
        resource_attributes['ci.pr_number'] AS pr_number,
        resource_attributes['ci.branch'] AS branch,
        -- GITHUB_SHA: on pull_request events the refs/pull/N/merge commit, so equal sha across
        -- runs means a byte-identical tree. ifNull matters: a missing map key reads as NULL, and
        -- in HogQL NULL != '' is true, so unstamped spans would otherwise pair on the NULL tree.
        ifNull(resource_attributes['ci.sha'], '') AS sha,
        coalesce(lanes.lane, '') AS lane,
        -- The emitter always stamps ci.run_id; the trace_id fallback (one trace per job) keeps an
        -- unstamped span from merging every execution of its test into one phantom run.
        coalesce(nullIf(resource_attributes['ci.run_id'], ''), spans.trace_id) AS run_id,
        ifNull(accurateCastOrNull(resource_attributes['ci.run_attempt'], 'Int64'), 1) AS attempt,
        timestamp AS span_timestamp,
        timestamp >= {date_from} AS is_current
    FROM posthog.trace_spans AS spans
    LEFT ANY JOIN (__LANES__) AS lanes ON spans.trace_id = lanes.trace_id
    WHERE service_name = {service_name}
        AND lower(resource_attributes['ci.repository']) = lower({repository})
        AND timestamp >= {scan_from}__DATE_TO__
        -- First-attempt passes are the whole passing corpus, which dwarfs the signal one, so they
        -- are never read wholesale: only re-run attempts' passes (the cross-attempt recovery arm)
        -- and first-attempt passes at a tree some run failed (the cross-run pairing arm, bounded
        -- by the failing set) are admitted.
        AND (
            attributes['test.outcome'] IN {signal_outcomes}
            OR (
                attributes['test.outcome'] = 'passed'
                AND resource_attributes['ci.run_attempt'] NOT IN ('', '1')
            )
            OR (
                attributes['test.outcome'] = 'passed'
                AND ifNull(resource_attributes['ci.sha'], '') != ''
                AND (name, resource_attributes['ci.sha']) IN (__FAILING_TREES__)
            )
        )
"""


def scan_placeholders(
    *,
    repository: str,
    date_from: datetime,
    scan_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, ast.Expr]:
    placeholders: dict[str, ast.Expr] = {
        "service_name": ast.Constant(value=CI_SERVICE_NAME),
        "signal_outcomes": ast.Constant(value=SIGNAL_OUTCOMES),
        "unowned_team": ast.Constant(value=UNOWNED_TEAM),
        "repository": ast.Constant(value=repository),
        "date_from": ast.Constant(value=date_from),
        "scan_from": ast.Constant(value=scan_from if scan_from is not None else date_from),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    return placeholders


def selector_from_nodeid(nodeid: str) -> str:
    """Best-effort runnable pytest selector for a span the CI reporter emitted before it stamped
    ``test.selector``. The nodeid folds the file/class boundary into '/' and drops '.py'
    ('posthog/api/test/test_x/TestX::test_y'); re-split on the convention that class segments are
    CamelCase and everything before them is the module file. Newer spans skip this: they carry the
    exact selector, built from JUnit's ``file`` where the boundary isn't guessed. Removable once every
    in-retention span carries ``test.selector`` (i.e. the emitter has been live longer than Traces
    retention).
    """
    class_path, sep, test_part = nodeid.partition("::")
    if not sep or "/" not in class_path:
        return nodeid
    segments = class_path.split("/")
    module_end = len(segments)
    while module_end > 1 and segments[module_end - 1][:1].isupper():
        module_end -= 1
    module = "/".join(segments[:module_end]) + ".py"
    return "::".join([module, *segments[module_end:], test_part])
