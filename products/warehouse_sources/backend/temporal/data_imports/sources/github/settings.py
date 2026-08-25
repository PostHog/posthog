from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


# Tests patch fields on these config records, so freezing them is a change of its own. The class
# stays tracked in dataclass_frozen_baseline.txt for that migration.
@dataclass  # nosemgrep: prefer-frozen-dataclasses -- tests mutate these config records
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
    # Parent fields to copy onto each child row, mapped to the child column name
    # (e.g. {"id": "team_id", "slug": "team_slug"}). Gives fan-out children the
    # parent context the child API omits; team_members rows are plain users.
    fan_out_include_parent_fields: Optional[dict[str, str]] = None
    # Extra static query params for the request (e.g. {"filter": "all"}).
    extra_params: Optional[dict[str, str]] = None
    # Hard cap on pages fetched per parent in a fan-out, to bound runaway
    # pagination. A structured warning is logged if the cap is reached.
    max_pages_per_parent: int = 50
    # First-sync floor: the very first incremental sync only reaches back this many
    # days instead of crawling the whole repo history. For a fan-out child it bounds
    # the parent walk; for a repo-wide endpoint with `since` support it becomes a
    # server-side `since` floor. The webhook carries steady-state, so only the
    # one-off backfill needs a bound; later syncs advance from the stored watermark
    # and ignore this. Zero means the poll does no backfill at all, which is what
    # marks a webhook-capable endpoint webhook-only.
    initial_lookback_days: Optional[int] = None
    # Steady-state reconciliation for a webhook-fed fan-out child whose events GitHub does not
    # always deliver: after each webhook drain, re-fan parents created within this many days so
    # child rows that never got a webhook (deployment statuses marked inactive) are still
    # collected from the list API. None = webhook drain only.
    webhook_reconcile_lookback_days: Optional[int] = None
    # Parent field bumped whenever a child row is created (deployments.updated_at). When set,
    # an incremental fan-out skips parents whose value predates the child watermark — they can
    # hold no unseen children — keeping the reconciliation window cheap to re-walk every sync.
    fan_out_parent_recency_field: Optional[str] = None
    # Query-param shape for the list request.
    #   "issue_list" — the original shape: per_page + state=all + a created/updated sort pair.
    #   "sorted"     — same minus `state`, whose enum differs per endpoint (the alert endpoints
    #                  reject `state=all`) while `sort`/`direction` are accepted as usual.
    #   "plain"      — per_page plus `extra_params` only, for endpoints that accept no sort at all
    #                  (or accept a different sort enum, e.g. milestones' due_on/completeness).
    param_style: Literal["issue_list", "sorted", "plain"] = "issue_list"
    # Endpoint honors GitHub's `since` filter, so an incremental sync is bounded server-side rather
    # than by walking pages until the watermark. (issues and commits predate this flag and are
    # matched by name in github.py.)
    supports_since_param: bool = False
    # Endpoint returns newest-first whatever params we send, so rows are emitted desc on every sync
    # — the first one included — and SourceResponse.sort_mode has to say so or the pipeline
    # checkpoints the watermark assuming ascending order. workflow_runs and deployments are the
    # original cases and are matched by name via _ALWAYS_NEWEST_FIRST_ENDPOINTS in github.py.
    always_desc: bool = False
    # A 404 on this endpoint means the resource does not exist for this repository rather than that
    # the repository or token is wrong, so the sync writes zero rows instead of failing. Issue types
    # and repository teams only exist under an organization owner, so a user-owned repo 404s on both
    # even with a perfectly good token. (The org-scoped endpoints predate this flag and are matched
    # by name via ORG_SCOPED_ENDPOINTS in github.py.)
    tolerate_not_found: bool = False


def _datetime_field(field: str) -> IncrementalField:
    return {
        "label": field,
        "type": IncrementalFieldType.DateTime,
        "field": field,
        "field_type": IncrementalFieldType.DateTime,
    }


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
        # The parent walk bounds on the PR's updated_at (the parent's own default cursor); the
        # invariant making that sound against the submitted_at watermark is documented at
        # parent_cursor_field in github.py.
        # One /reviews call per PR: any poll backfill re-fans every PR bumped for any reason, and a
        # historical crawl is one request per PR over the repo's whole life. So poll does no
        # backfill: the pull_request_review webhook is the source of truth for reviews, and the
        # poll only re-fans the tiny window since the latest synced review. Repos that want history
        # should run a deliberate one-off backfill, not pay for it on every connect.
        initial_lookback_days=0,
        # A review can emit several webhook events sharing an id (submitted, then edited or
        # dismissed) and the delta merge doesn't dedupe within a batch, so collapse each batch to
        # one row per id. submitted_at is constant across those events, so they always tie; the
        # dedupe transformer breaks ties by keeping the later-arriving row (rows arrive in
        # delivery order), so a submit followed by a dismissal in one drain keeps the dismissal.
        version_keys=["submitted_at"],
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
        # Webhook-only marker, like workflow_jobs and reviews: the webhook is the source of truth.
        # initial_lookback_days == 0 makes source.py report this schema as webhook_only, activates
        # webhook mode from the first sync (skips the initial_sync_complete gate in github.py), and
        # makes the poll path yield no rows instead of crawling the full /actions/runs history.
        # Crawling a busy repo's whole run history on connect is huge against a shared, rate-limited
        # budget. History, if wanted, is a deliberate one-off backfill.
        initial_lookback_days=0,
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
    "deployments": GithubEndpointConfig(
        name="deployments",
        path="/repos/{repository}/deployments",
        partition_key="created_at",
        incremental_fields=[
            # The deployments list endpoint returns newest-first by created_at and (like
            # /actions/runs) does not honor sort/direction, so created_at is the only viable
            # cursor. We sync incrementally by paginating newest-first and stopping once we cross
            # below the cursor (see github.py). created_at is immutable; a deployment's latest
            # state lives on its deployment_statuses children and on updated_at, so the
            # created_at cursor won't refresh a deployment once newer ones land — that is handled
            # by the deployment webhook, not by re-scanning history.
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="created_at",
        sort_mode="desc",  # API returns newest-first and ignores sort/direction, like workflow_runs
        # deployment carries updated_at (bumped when a new status is added), the recency key so a
        # completed deployment is never frozen by a stale earlier webhook event.
        version_keys=["updated_at"],
        # Webhook-only marker, like workflow_runs: the deployment webhook is the source of truth.
        # initial_lookback_days == 0 makes source.py report this schema as webhook_only, activates
        # webhook mode from the first sync, and makes the poll path yield no rows instead of
        # crawling the full /deployments history against a shared, rate-limited budget. History,
        # if wanted, is a deliberate one-off backfill.
        initial_lookback_days=0,
    ),
    "deployment_statuses": GithubEndpointConfig(
        name="deployment_statuses",
        # Child of deployments: {deployment_id} is filled per parent deployment during fan-out.
        # GitHub has no repo-wide deployment-statuses list, so a deployment's status history (the
        # success/failure/inactive transitions that mark a rollback) can only be assembled by
        # fanning out over deployments one at a time.
        path="/repos/{repository}/deployments/{deployment_id}/statuses",
        partition_key="created_at",  # Set at status creation; immutable and non-null.
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="created_at",
        # Deployment-status ids are globally unique (like review ids), so no composite key is
        # needed even though this is a fan-out child.
        primary_key="id",
        sort_mode="desc",  # Rows land parent-newest-first, same as workflow_jobs and reviews.
        fan_out_parent="deployments",
        fan_out_path_param="deployment_id",
        fan_out_parent_field="id",
        # The raw status only carries the deployment API URL, so inject the deployment id for
        # trivial attribution joins against the deployments table (mirrors reviews' pr_number).
        fan_out_include_parent_fields={"id": "deployment_id"},
        # Webhook-first (zero first-sync backfill), but not webhook-alone: GitHub never fires a
        # deployment_status webhook for the inactive state, so a pure webhook feed would miss
        # rollbacks and auto_inactive transitions, leaving a superseded deployment looking current.
        # Each sync therefore chases the webhook drain with a bounded reconciliation fan-out over
        # deployments created in the last 30 days; the updated_at recency skip keeps that to
        # parents that actually gained a status since the child watermark.
        initial_lookback_days=0,
        webhook_reconcile_lookback_days=30,
        fan_out_parent_recency_field="updated_at",
        # A deployment status is append-only (each transition is a new, immutable id), so no
        # webhook dedupe is needed — unlike reviews/runs, one id never emits multiple events.
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
    # --- Repository metadata --------------------------------------------------------------
    "repository": GithubEndpointConfig(
        name="repository",
        # Returns the repository object itself rather than a list; a body transform in github.py
        # wraps it as the single row of a one-row-per-repo table.
        path="/repos/{repository}",
        incremental_fields=[],
        param_style="plain",
    ),
    "topics": GithubEndpointConfig(
        name="topics",
        # {"names": [...]} — the body transform emits one row per topic.
        path="/repos/{repository}/topics",
        incremental_fields=[],
        primary_key="name",
        param_style="plain",
    ),
    "languages": GithubEndpointConfig(
        name="languages",
        # A {language: bytes} map — the body transform emits one row per language.
        path="/repos/{repository}/languages",
        incremental_fields=[],
        primary_key="language",
        param_style="plain",
    ),
    "community_profile": GithubEndpointConfig(
        name="community_profile",
        path="/repos/{repository}/community/profile",
        incremental_fields=[],
        # One row per repository, so the injected repository column is the only stable key.
        primary_key="repository",
        param_style="plain",
    ),
    "repository_activity": GithubEndpointConfig(
        name="repository_activity",
        # Pushes, force pushes, merges, and branch creations and deletions, repo-wide. This is the
        # only place force pushes and branch deletions are visible at all: they rewrite or remove
        # history, so nothing in commits or pull_requests records that they happened.
        # The endpoint takes no `since` filter but answers newest-first, so incremental syncs
        # paginate down and stop at the watermark, the same way issue_events does.
        path="/repos/{repository}/activity",
        partition_key="timestamp",  # When the activity happened; immutable.
        incremental_fields=[_datetime_field("timestamp")],
        default_incremental_field="timestamp",
        param_style="plain",
        # desc is already the endpoint's default, but the descending walk is what makes the
        # watermark stop correct, so send it rather than depend on the default staying put.
        extra_params={"direction": "desc"},
        sort_mode="desc",
        always_desc=True,
    ),
    "repository_teams": GithubEndpointConfig(
        name="repository_teams",
        # The teams granted access to this repository, with the permission level each holds. Unlike
        # the org-wide teams table this is repo-scoped, so it answers "who owns this repo" without
        # the org membership grant.
        path="/repos/{repository}/teams",
        incremental_fields=[],
        param_style="plain",
        # GitHub answers 404 rather than 403 when the caller cannot see a repository's teams, and a
        # user-owned repo has no teams at all, so a default connection could enable a table that
        # only ever stays empty. Leave it deselected and let org-owned repos opt in.
        should_sync_default=False,
        tolerate_not_found=True,
    ),
    # --- Issue and review discussion ------------------------------------------------------
    "issue_comments": GithubEndpointConfig(
        name="issue_comments",
        path="/repos/{repository}/issues/comments",
        partition_key="created_at",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
        default_incremental_field="updated_at",
        param_style="sorted",
        supports_since_param=True,
        # A comment is editable, so created/edited/deleted deliveries for one id can land in the
        # same webhook batch. GitHub bumps updated_at on every edit, so it ranks them; the delta
        # merge does not dedupe within a batch, so without this the row keeps whichever event
        # happened to arrive last rather than the latest edit.
        version_keys=["updated_at"],
        # Bound the bootstrap: without a floor the first sync walks every comment ever written
        # before webhook mode can activate (webhook_enabled needs initial_sync_complete), which on
        # a large repo is thousands of requests against the shared budget. Steady state is the
        # webhook, or a `since`-bounded poll, so only the backfill window is at stake; deeper
        # history is a deliberate one-off backfill.
        initial_lookback_days=14,
    ),
    "pull_request_comments": GithubEndpointConfig(
        name="pull_request_comments",
        # Repo-wide review comments (the inline code comments on pull requests), so unlike reviews
        # this needs no fan-out over pull requests.
        path="/repos/{repository}/pulls/comments",
        partition_key="created_at",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
        default_incremental_field="updated_at",
        param_style="sorted",
        supports_since_param=True,
        version_keys=["updated_at"],  # Editable, same as issue_comments.
        initial_lookback_days=14,  # Bound the bootstrap, same as issue_comments.
    ),
    "commit_comments": GithubEndpointConfig(
        name="commit_comments",
        # The third comment surface, alongside issue_comments and pull_request_comments: comments
        # left on a commit directly rather than through an issue or a pull request review.
        path="/repos/{repository}/comments",
        partition_key="created_at",
        # Rows come back ordered by ascending id and the endpoint takes no `since` filter or sort,
        # so an incremental sync would still walk every page. Full refresh only, which is why the
        # commit_comment webhook matters more here than for the other two comment tables: it is the
        # only way this table stops re-pulling the whole collection on every sync.
        incremental_fields=[],
        param_style="plain",
        version_keys=["updated_at"],  # Editable, same as issue_comments.
    ),
    "issue_types": GithubEndpointConfig(
        name="issue_types",
        # Lookup table for the issue type an issue carries (Bug, Feature, Task, plus whatever the
        # organization defines). issues stores it as a nested object per row, so without this there
        # is nothing to group by when a type is renamed or retired.
        path="/repos/{repository}/issue-types",
        incremental_fields=[],
        param_style="plain",
        # Issue types are inherited from the organization owner, so a user-owned repository 404s.
        tolerate_not_found=True,
    ),
    "issue_events": GithubEndpointConfig(
        name="issue_events",
        # Labeled / assigned / closed / reopened transitions, repo-wide. The endpoint takes no time
        # filter and always answers newest-first, so incremental syncs paginate down and stop at the
        # watermark, the same way workflow_runs does.
        path="/repos/{repository}/issues/events",
        partition_key="created_at",
        incremental_fields=[_datetime_field("created_at")],
        default_incremental_field="created_at",
        param_style="plain",
        sort_mode="desc",
        always_desc=True,
    ),
    "labels": GithubEndpointConfig(
        name="labels",
        path="/repos/{repository}/labels",
        incremental_fields=[],
        param_style="plain",
    ),
    "milestones": GithubEndpointConfig(
        name="milestones",
        # Its sort enum is due_on/completeness, so the generic created/updated sort would be
        # rejected — send only state and paginate in the API's default order.
        path="/repos/{repository}/milestones",
        partition_key="created_at",
        incremental_fields=[],
        param_style="plain",
        extra_params={"state": "all"},
    ),
    # --- Git refs and people ---------------------------------------------------------------
    "branches": GithubEndpointConfig(
        name="branches",
        path="/repos/{repository}/branches",
        incremental_fields=[],
        primary_key="name",  # Branches carry no id; the name is unique within the repository.
        param_style="plain",
    ),
    "tags": GithubEndpointConfig(
        name="tags",
        path="/repos/{repository}/tags",
        incremental_fields=[],
        primary_key="name",  # Tags carry no id either.
        param_style="plain",
    ),
    "contributors": GithubEndpointConfig(
        name="contributors",
        path="/repos/{repository}/contributors",
        incremental_fields=[],
        param_style="plain",
    ),
    "collaborators": GithubEndpointConfig(
        name="collaborators",
        path="/repos/{repository}/collaborators",
        incremental_fields=[],
        param_style="plain",
        # Needs push access to the repository, which a read-only connection lacks; leave it
        # deselected so a default connection doesn't enable a table whose first sync would 403.
        should_sync_default=False,
    ),
    "subscribers": GithubEndpointConfig(
        name="subscribers",
        path="/repos/{repository}/subscribers",
        incremental_fields=[],
        param_style="plain",
    ),
    "forks": GithubEndpointConfig(
        name="forks",
        # Defaults to sort=newest, so rows arrive newest-first on every sync and incremental
        # pagination can stop at the watermark.
        path="/repos/{repository}/forks",
        partition_key="created_at",
        incremental_fields=[_datetime_field("created_at")],
        default_incremental_field="created_at",
        param_style="plain",
        extra_params={"sort": "newest"},
        sort_mode="desc",
        always_desc=True,
    ),
    # --- Deploys and CI --------------------------------------------------------------------
    # deployments and deployment_statuses are defined above with full webhook-fed incremental sync.
    "environments": GithubEndpointConfig(
        name="environments",
        path="/repos/{repository}/environments",
        partition_key="created_at",
        incremental_fields=[],
        param_style="plain",
        response_data_path="environments",
    ),
    "workflows": GithubEndpointConfig(
        name="workflows",
        path="/repos/{repository}/actions/workflows",
        partition_key="created_at",
        incremental_fields=[],
        param_style="plain",
        response_data_path="workflows",
    ),
    "artifacts": GithubEndpointConfig(
        name="artifacts",
        path="/repos/{repository}/actions/artifacts",
        partition_key="created_at",
        incremental_fields=[],
        param_style="plain",
        response_data_path="artifacts",
    ),
    "runners": GithubEndpointConfig(
        name="runners",
        path="/repos/{repository}/actions/runners",
        incremental_fields=[],
        param_style="plain",
        response_data_path="runners",
        # Self-hosted runners need the repository administration permission.
        should_sync_default=False,
    ),
    "actions_caches": GithubEndpointConfig(
        name="actions_caches",
        path="/repos/{repository}/actions/caches",
        partition_key="created_at",
        incremental_fields=[],
        param_style="plain",
        response_data_path="actions_caches",
    ),
    "check_runs": GithubEndpointConfig(
        name="check_runs",
        # Child of commits: {ref} is filled per parent commit during fan-out. GitHub exposes no
        # repo-wide check-runs list, so per-commit CI signal can only be assembled one commit at a
        # time, the same way reviews are assembled per pull request.
        path="/repos/{repository}/commits/{ref}/check-runs",
        # started_at is nullable while a run is queued, so it works as a cursor but not as a
        # partition key — this table stays unpartitioned.
        incremental_fields=[_datetime_field("started_at"), _datetime_field("completed_at")],
        default_incremental_field="started_at",
        # Check run ids are globally unique (GitHub exposes /repos/{repo}/check-runs/{id}), so no
        # composite key is needed even though this is a fan-out child.
        primary_key="id",
        sort_mode="desc",  # Rows land parent-newest-first, like workflow_jobs and reviews.
        response_data_path="check_runs",
        fan_out_parent="commits",
        fan_out_path_param="ref",
        fan_out_parent_field="sha",
        # filter=all returns every check run for the ref, not just the latest per check name —
        # required for re-run and flake analysis.
        extra_params={"filter": "all"},
        # Webhook-only marker, like reviews: the poll costs one call per commit, so any poll mode
        # is a per-commit fan-out over a shared, rate-limited budget however tight the window is.
        # initial_lookback_days == 0 makes source.py offer this schema webhook-only, activates
        # webhook mode from the first sync, and makes the poll path yield no rows. History, if
        # wanted, is a deliberate one-off backfill.
        initial_lookback_days=0,
        # A busy repo produces check runs at commit x check-name grain, which is far more volume
        # than most connections want, so leave it deselected and let users opt in.
        should_sync_default=False,
        # A check run emits queued -> in_progress -> completed events sharing an id and carries no
        # updated_at, so rank by how far the run progressed: completed_at (terminal) outranks
        # started_at, and both are NULL while queued, so NULLs-last ordering keeps the latest state.
        version_keys=["completed_at", "started_at"],
    ),
    "commit_statuses": GithubEndpointConfig(
        name="commit_statuses",
        # Child of commits, like check_runs: the statuses API is per-ref only.
        path="/repos/{repository}/commits/{ref}/statuses",
        partition_key="created_at",
        incremental_fields=[_datetime_field("created_at"), _datetime_field("updated_at")],
        default_incremental_field="created_at",
        # GitHub documents no single-status lookup, so treat the id as unique only within its
        # commit and key on the injected sha as well — a fan-out child's key must be unique
        # table-wide or every later merge multi-matches.
        primary_key=["commit_sha", "id"],
        sort_mode="desc",
        fan_out_parent="commits",
        fan_out_path_param="ref",
        fan_out_parent_field="sha",
        # A status carries no sha of its own, so inject the commit it was posted against. The Hog
        # template fills the same column from the `status` event's top-level `sha`, so webhook rows
        # carry both halves of the composite key too.
        fan_out_include_parent_fields={"sha": "commit_sha"},
        # Webhook-only marker, like check_runs: the poll is a per-commit fan-out, and it also
        # bounds the parent walk on the commit's immutable created_at with no
        # fan_out_parent_recency_field, so a status posted after the watermark passed its commit is
        # never fetched. The `status` webhook carries every status as it is posted, which fixes both.
        initial_lookback_days=0,
        # Statuses arrive at commit x context grain on a busy repo, so leave the table deselected
        # and let users opt in.
        should_sync_default=False,
        # No version_keys on purpose: statuses are append-only (a re-run posts a new status id
        # rather than mutating one), so there is nothing to collapse within a batch. The dedupe
        # transformer would also be wrong here, because it ranks on the first primary-key column
        # only, which is commit_sha for this composite key, and would keep one status per commit.
    ),
    # --- Security posture ------------------------------------------------------------------
    "code_scanning_alerts": GithubEndpointConfig(
        name="code_scanning_alerts",
        path="/repos/{repository}/code-scanning/alerts",
        partition_key="created_at",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
        default_incremental_field="updated_at",
        # Alerts are numbered within the repository and carry no id.
        primary_key="number",
        param_style="sorted",
        # Needs the code scanning alerts read grant, which a plain repo connection lacks.
        should_sync_default=False,
    ),
    "dependabot_alerts": GithubEndpointConfig(
        name="dependabot_alerts",
        path="/repos/{repository}/dependabot/alerts",
        partition_key="created_at",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
        default_incremental_field="updated_at",
        primary_key="number",
        param_style="sorted",
        should_sync_default=False,
    ),
    "secret_scanning_alerts": GithubEndpointConfig(
        name="secret_scanning_alerts",
        path="/repos/{repository}/secret-scanning/alerts",
        partition_key="created_at",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
        default_incremental_field="updated_at",
        primary_key="number",
        param_style="sorted",
        # Ask GitHub to leave the leaked credential out of the response. github.py also strips it
        # from every row, so the guarantee doesn't rest on the pinned API version honoring this.
        extra_params={"hide_secret": "true"},
        should_sync_default=False,
    ),
    "security_advisories": GithubEndpointConfig(
        name="security_advisories",
        path="/repos/{repository}/security-advisories",
        partition_key="created_at",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
        default_incremental_field="updated_at",
        primary_key="ghsa_id",  # Repository advisories are keyed by GHSA id, not a numeric id.
        param_style="sorted",
        should_sync_default=False,
    ),
    "dependency_sbom": GithubEndpointConfig(
        name="dependency_sbom",
        # One SPDX document per repository; the body transform emits one row per package, which is
        # the grain a dependency inventory is actually queried at.
        path="/repos/{repository}/dependency-graph/sbom",
        incremental_fields=[],
        primary_key="spdx_id",
        param_style="plain",
    ),
    "rulesets": GithubEndpointConfig(
        name="rulesets",
        path="/repos/{repository}/rulesets",
        partition_key="created_at",
        incremental_fields=[],
        param_style="plain",
    ),
    "hooks": GithubEndpointConfig(
        name="hooks",
        path="/repos/{repository}/hooks",
        partition_key="created_at",
        incremental_fields=[],
        param_style="plain",
        # Reading webhooks needs admin:repo_hook (or the repository webhooks read permission).
        should_sync_default=False,
    ),
    # --- Traffic and statistics ------------------------------------------------------------
    # GitHub only retains traffic for the last 14 days and recomputes the stats aggregates
    # asynchronously, so these are full-refresh tables that upsert on each sync.
    "traffic_views": GithubEndpointConfig(
        name="traffic_views",
        path="/repos/{repository}/traffic/views",
        partition_key="timestamp",
        incremental_fields=[],
        primary_key="timestamp",
        param_style="plain",
        response_data_path="views",
        should_sync_default=False,  # Traffic needs push access to the repository.
    ),
    "traffic_clones": GithubEndpointConfig(
        name="traffic_clones",
        path="/repos/{repository}/traffic/clones",
        partition_key="timestamp",
        incremental_fields=[],
        primary_key="timestamp",
        param_style="plain",
        response_data_path="clones",
        should_sync_default=False,
    ),
    "traffic_referrers": GithubEndpointConfig(
        name="traffic_referrers",
        path="/repos/{repository}/traffic/popular/referrers",
        incremental_fields=[],
        primary_key="referrer",
        param_style="plain",
        should_sync_default=False,
    ),
    "traffic_paths": GithubEndpointConfig(
        name="traffic_paths",
        path="/repos/{repository}/traffic/popular/paths",
        incremental_fields=[],
        primary_key="path",
        param_style="plain",
        should_sync_default=False,
    ),
    "contributor_stats": GithubEndpointConfig(
        name="contributor_stats",
        path="/repos/{repository}/stats/contributors",
        incremental_fields=[],
        # The author is nested; github.py flattens the id and login onto the row.
        primary_key="author_id",
        param_style="plain",
    ),
    "commit_activity_stats": GithubEndpointConfig(
        name="commit_activity_stats",
        path="/repos/{repository}/stats/commit_activity",
        incremental_fields=[],
        # week is the unix timestamp of the week start, so it identifies the bucket.
        primary_key="week",
        param_style="plain",
    ),
    "participation_stats": GithubEndpointConfig(
        name="participation_stats",
        # {"all": [...], "owner": [...]} — a rolling 52-week window, so it is one row per repo
        # rather than one per week (the week offsets shift on every sync).
        path="/repos/{repository}/stats/participation",
        incremental_fields=[],
        primary_key="repository",
        param_style="plain",
    ),
    "code_frequency_stats": GithubEndpointConfig(
        name="code_frequency_stats",
        # Returns positional arrays ([week, additions, deletions]); the body transform names them.
        path="/repos/{repository}/stats/code_frequency",
        incremental_fields=[],
        primary_key="week",
        param_style="plain",
    ),
    "punch_card_stats": GithubEndpointConfig(
        name="punch_card_stats",
        # Returns positional arrays ([day, hour, commits]); the body transform names them. One row
        # per weekday/hour bucket, so the whole table is at most 168 rows.
        path="/repos/{repository}/stats/punch_card",
        incremental_fields=[],
        primary_key=["day", "hour"],
        param_style="plain",
    ),
}

ENDPOINTS = tuple(GITHUB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITHUB_ENDPOINTS.items()
}

# The grant a connection needs before GitHub will answer this endpoint, keyed the way GitHub names
# it in an installation's permission set, so the picker can compare it against the permissions the
# installation actually holds. Endpoints not listed here need no grant beyond the metadata/contents
# read that every connection is validated for at connect time, so a denial on those is not a
# per-table gap.
ENDPOINT_REQUIRED_PERMISSION: dict[str, str] = {
    "issues": "issues",
    "issue_comments": "issues",
    "issue_events": "issues",
    "issue_types": "issues",
    "labels": "issues",
    "milestones": "issues",
    "pull_requests": "pull_requests",
    "pull_request_comments": "pull_requests",
    "reviews": "pull_requests",
    "workflow_runs": "actions",
    "workflow_jobs": "actions",
    "workflows": "actions",
    "artifacts": "actions",
    "actions_caches": "actions",
    "check_runs": "checks",
    "commit_statuses": "statuses",
    "environments": "environments",
    "deployments": "deployments",
    "deployment_statuses": "deployments",
    "code_scanning_alerts": "security_events",
    "secret_scanning_alerts": "secret_scanning_alerts",
    "dependabot_alerts": "vulnerability_alerts",
    "security_advisories": "repository_advisories",
    "runners": "administration",
    "traffic_views": "administration",
    "traffic_clones": "administration",
    "traffic_referrers": "administration",
    "traffic_paths": "administration",
    "hooks": "repository_hooks",
    "teams": "members",
    "team_members": "members",
}

# Prefix of every per-endpoint grant-denial message _fetch_page raises. GithubSource's
# get_non_retryable_errors keys its catch-all on this exact string: GitHub phrases denials per
# endpoint ("Must have push access to view repository collaborators"), so without the shared prefix
# those wordings would match no key and the job would retry a denial forever instead of disabling
# the schema.
GRANT_DENIAL_PREFIX = "GitHub can't read this table"

# What to ask for, as (name on a fine-grained token or app installation, scope on a classic token).
# The three name the same grant differently, so the message carries both rather than making the
# reader translate. _grant_hint in github.py builds the sentence, which keeps the wording in one
# place and out of the user-facing string, where markdown does not render.
GRANT_NAMES: dict[str, tuple[str, str]] = {
    "issues": ("Issues: read", "repo"),
    "pull_requests": ("Pull requests: read", "repo"),
    "actions": ("Actions: read", "repo"),
    "checks": ("Checks: read", "repo"),
    "statuses": ("Commit statuses: read", "repo:status"),
    "environments": ("Environments: read", "repo"),
    "deployments": ("Deployments: read", "repo_deployment"),
    "security_events": ("Code scanning alerts: read", "security_events"),
    "secret_scanning_alerts": ("Secret scanning alerts: read", "repo"),
    "vulnerability_alerts": ("Dependabot alerts: read", "security_events"),
    "repository_advisories": ("Repository security advisories: read", "repo"),
    "administration": ("Administration: read", "repo"),
    "repository_hooks": ("Webhooks: read", "admin:repo_hook"),
    "members": ("Members: read on the organization", "read:org"),
}
