from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class GithubEndpointConfig:
    name: str
    path: str  # Path template with {repository}, {organization}, and fan-out placeholders
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    page_size: int = 100  # GitHub default, max is 100
    sort_mode: Literal["asc", "desc"] = "asc"
    # Primary key for upsert operations. A list declares a composite key, required for
    # fan-out children whose row id is only unique within a parent (a user can belong to
    # two teams, so team_members keys on ["team_id", "id"] to stay unique table-wide).
    primary_key: str | list[str] = "id"
    # False leaves the table deselected in the schema picker and disabled by one-shot setup.
    # Use for tables needing grants beyond the repo scope validated at source-create, so a
    # default connection doesn't enable a table whose first sync would 403.
    should_sync_default: bool = True
    # Ordered columns (compared newest-first, NULLs last) that rank webhook events sharing a
    # primary key, so the source collapses a batch to the latest state per id before it reaches the
    # delta merge (which doesn't dedupe within a batch). GitHub emits one run/job as separate
    # queued -> in_progress -> completed events; without this the merge keeps whichever landed last
    # in batch order, freezing rows pre-completion. None = no webhook dedup (poll-only endpoints).
    version_keys: Optional[list[str]] = None
    # Body key to drill into when the API wraps results in an envelope
    # (e.g. /actions/runs returns {"total_count": N, "workflow_runs": [...]}).
    # None means the response body is itself the list.
    response_data_path: Optional[str] = None
    # Fan-out: name of the parent endpoint whose rows seed this child's path.
    # When set, the endpoint is fetched by walking the parent (reusing its
    # pagination/incremental bounding) and calling this child once per parent
    # row, substituting a parent field into the child path placeholder.
    fan_out_parent: Optional[str] = None
    # Fan-out path placeholder to fill from the parent (e.g. "run_id" -> {run_id},
    # "team_slug" -> {team_slug}) and the parent field to read for it.
    fan_out_path_param: str = "run_id"
    fan_out_parent_field: str = "id"
    # Which field on the PARENT row bounds the fan-out walk (desc early-stop + per-parent skip).
    # Decoupled from the child's own incremental field on purpose: a child can be keyed on a
    # timestamp the parent row doesn't carry (reviews sync on submitted_at, which lives on the
    # review, not the pull request). When None the walk falls back to the child incremental field
    # then the parent default, which keeps workflow_jobs unchanged (both sides use created_at).
    fan_out_parent_cursor_field: Optional[str] = None
    # Parent fields to copy onto each child row, mapped to the child column name
    # (e.g. {"id": "team_id", "slug": "team_slug"}). Gives fan-out children the
    # parent context the child API omits; team_members rows are plain users.
    fan_out_include_parent_fields: Optional[dict[str, str]] = None
    # Extra static query params for the request (e.g. {"filter": "all"}).
    extra_params: Optional[dict[str, str]] = None
    # Hard cap on pages fetched per parent in a fan-out, to bound runaway
    # pagination. A structured warning is logged if the cap is reached.
    max_pages_per_parent: int = 50
    # First-sync floor: when set, the very first incremental sync only fans out
    # over parents created within this many days, instead of crawling the whole
    # repo history. The webhook carries steady-state, so only the one-off backfill
    # needs a bound; later syncs advance from the stored watermark and ignore this.
    initial_lookback_days: Optional[int] = None


GITHUB_ENDPOINTS: dict[str, GithubEndpointConfig] = {
    "issues": GithubEndpointConfig(
        name="issues",
        path="/repos/{repository}/issues",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="updated_at",
    ),
    "pull_requests": GithubEndpointConfig(
        name="pull_requests",
        path="/repos/{repository}/pulls",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="updated_at",
        sort_mode="desc",  # Use descending sort to enable incremental sync
    ),
    "reviews": GithubEndpointConfig(
        name="reviews",
        # Child of pull_requests: {pull_number} is filled per parent PR during fan-out. GitHub has no
        # repo-wide reviews list, so review metrics (reviews per PR, time-to-first-review, approval
        # latency) can only be assembled by fanning out over pull requests one at a time.
        path="/repos/{repository}/pulls/{pull_number}/reviews",
        partition_key="submitted_at",  # Immutable once submitted; non-null after the PENDING filter below.
        incremental_fields=[
            {
                "label": "submitted_at",
                "type": IncrementalFieldType.DateTime,
                "field": "submitted_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="submitted_at",
        # Review ids are globally unique, so no composite key is needed even though reviews are a
        # fan-out child (the composite-key rule only applies to children whose id is unique just
        # within a parent, like team_members).
        primary_key="id",
        sort_mode="desc",  # Rows land parent-newest-first, same as workflow_jobs.
        fan_out_parent="pull_requests",
        fan_out_path_param="pull_number",
        fan_out_parent_field="number",
        # The raw review only carries pull_request_url, so inject the PR number for trivial attribution
        # joins against the pull_requests table.
        fan_out_include_parent_fields={"number": "pr_number"},
        # Bound the parent walk on the PR's updated_at, NOT the child's submitted_at (which pull
        # requests don't carry). Submitting a review bumps the PR's updated_at, so any PR with a
        # review newer than the child watermark necessarily has updated_at above it; PRs bumped for
        # other reasons get re-fanned harmlessly since reviews upsert by id.
        fan_out_parent_cursor_field="updated_at",
        # Full-history backfill would be one request per PR over the repo's whole life (tens of
        # thousands of requests). Floor the first incremental sync at 30 days of PR updates; older
        # history is a deliberate one-off backfill, not paid for on every connect.
        initial_lookback_days=30,
        # Reviews need only the repo Pull requests read grant the source already validates at
        # create, unlike the org-scoped teams tables, so leave the table selectable by default.
        should_sync_default=True,
    ),
    "commits": GithubEndpointConfig(
        name="commits",
        path="/repos/{repository}/commits",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",  # Flattened from commit.author.date
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="created_at",
        primary_key="sha",  # Commits use sha as unique identifier
        sort_mode="desc",  # GitHub commits API always returns newest-first, ignores sort/direction params
    ),
    "stargazers": GithubEndpointConfig(
        name="stargazers",
        path="/repos/{repository}/stargazers",
        partition_key="starred_at",
        incremental_fields=[],  # No incremental support
    ),
    "releases": GithubEndpointConfig(
        name="releases",
        path="/repos/{repository}/releases",
        partition_key="created_at",
        incremental_fields=[],  # No incremental support
    ),
    "workflow_runs": GithubEndpointConfig(
        name="workflow_runs",
        path="/repos/{repository}/actions/runs",
        partition_key="created_at",
        incremental_fields=[
            # The list endpoint returns newest-first by created_at and exposes
            # no updated_at filter/sort, so created_at is the only viable
            # cursor. We sync incrementally by paginating newest-first and
            # stopping once we cross below the cursor (see github.py), mirroring
            # how pull_requests/commits scroll desc. We deliberately do NOT send
            # the server-side `created` filter: GitHub caps any filtered search
            # to 1,000 results, which would silently truncate busy repos.
            #
            # created_at is immutable, but a run's status/conclusion mutate
            # after it first appears. The created_at cursor only refreshes runs
            # at/above the watermark, so a run that completes well after newer
            # runs landed won't be picked up here — that's handled by the
            # workflow_run webhook (followup), not by re-scanning history.
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="created_at",
        sort_mode="desc",  # API always returns newest-first; sort/direction are ignored
        response_data_path="workflow_runs",
        # workflow_run carries updated_at, which GitHub bumps on every status change — the natural
        # recency key so a completed run is never frozen by a stale earlier webhook event.
        version_keys=["updated_at"],
    ),
    "workflow_jobs": GithubEndpointConfig(
        name="workflow_jobs",
        # Child of workflow_runs: {run_id} is filled per parent run during fan-out.
        path="/repos/{repository}/actions/runs/{run_id}/jobs",
        partition_key="created_at",  # Set at job creation; non-null even while queued/running.
        incremental_fields=[
            # The jobs endpoint exposes no server-side time filter, so workflow_jobs
            # cannot have its own cursor. We bound incremental syncs at the parent:
            # walk workflow_runs newest-first, stop once run.created_at crosses below
            # the watermark, and fan out jobs only for runs at/above it (see
            # github.py). Jobs upsert by id, so re-reading a boundary run is harmless.
            #
            # Same created_at-cursor staleness as workflow_runs applies: a run whose
            # jobs finish well after newer runs have landed won't be re-fanned-out
            # once it drops below the watermark. The eventual fix is the workflow_run
            # webhook (followup), not re-scanning history.
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="created_at",
        sort_mode="desc",  # Emitted parent-newest-first, so jobs land newest-first too.
        response_data_path="jobs",
        fan_out_parent="workflow_runs",
        # filter=all returns jobs across every run_attempt (retries), not just the
        # latest execution — required for retry/runner-utilization analysis.
        extra_params={"filter": "all"},
        # One /jobs call per run, and a busy repo produces tens of thousands of runs
        # per day (every push, re-run, scheduled trigger, and matrix leg is a run —
        # not just PRs). At that volume even a few days of fan-out is hundreds of
        # thousands of requests against a shared, rate-limited OAuth budget. So poll
        # does no historical backfill: the webhook is the source of truth for jobs.
        # With a zero-day floor the first sync fans out over nothing, the watermark
        # stays unset, and once webhook rows land the poll only re-fans the tiny
        # window since the latest job. Repos that genuinely want history should run a
        # deliberate one-off backfill, not pay for it on every connect.
        initial_lookback_days=0,
        # workflow_job has no updated_at, so rank by how far the job progressed: completed_at
        # (terminal) outranks started_at (running) outranks created_at (queued). Each is NULL until
        # the job reaches that stage, so NULLs-last ordering keeps the latest state.
        version_keys=["completed_at", "started_at", "created_at"],
    ),
    "teams": GithubEndpointConfig(
        name="teams",
        # Org-scoped: {organization} is derived from the repository owner (owner/repo -> owner).
        path="/orgs/{organization}/teams",
        # The teams endpoint exposes no timestamps or server-side time filter, so there is no
        # cursor to sync incrementally on, so full refresh each sync (data volume is tiny).
        incremental_fields=[],
        # Needs the org Members: Read grant (read:org on PATs), which repo-scoped connections
        # lack, and 404s on user-owned repos. Off by default so a fresh source doesn't enable
        # a table whose first sync fails; the picker's permission probe explains the grant.
        should_sync_default=False,
    ),
    "team_members": GithubEndpointConfig(
        name="team_members",
        # Child of teams: {team_slug} is filled per parent team during fan-out.
        path="/orgs/{organization}/teams/{team_slug}/members",
        incremental_fields=[],  # Member list has no timestamps either; full refresh only.
        # Composite key: a user in two teams must be two distinct rows, and a fan-out child's
        # key must be unique table-wide or the delta merge multi-matches and degrades every sync.
        primary_key=["team_id", "id"],
        fan_out_parent="teams",
        fan_out_path_param="team_slug",
        fan_out_parent_field="slug",
        # Member rows are plain user objects with no team context, so inject it from the parent team.
        fan_out_include_parent_fields={"id": "team_id", "slug": "team_slug", "name": "team_name"},
        should_sync_default=False,  # Same org grant requirement as teams.
        # The default cap (50 pages, sized for per-run job lists) would silently truncate a team
        # past 5,000 members at 100/page. 400 pages bounds a runaway paginator at 40,000
        # memberships per team while clearing any plausible real team; the cap still logs.
        max_pages_per_parent=400,
    ),
}

ENDPOINTS = tuple(GITHUB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITHUB_ENDPOINTS.items()
}
