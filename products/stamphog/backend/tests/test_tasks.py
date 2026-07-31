import uuid
from typing import Any

import pytest
from unittest.mock import patch

from django.core.cache import cache
from django.utils.dateparse import parse_datetime

from posthog.models import Project, Team
from posthog.models.instance_setting import override_instance_config
from posthog.models.scoping import team_scope

from products.stamphog.backend.facade.enums import ReviewMode, ReviewRunStatus
from products.stamphog.backend.models import PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.tasks.tasks import (
    _INBOX_OPT_OUT_DISMISS_MESSAGE,
    _upsert_pull_request,
    process_inbox_pr_review,
    process_installation_event,
    process_pull_request_event,
)
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES
from products.tasks.backend.facade.contracts import SignalImplementationRunDTO

REPO = "acme/widgets"
INSTALLATION_ID = "1001"
# The instance's PostHog Code App slug: genuine self-driving PRs are authored by <slug>[bot], the
# identity `_is_self_driving_pr` requires. The self-driving fixtures below author as this bot.
APP_SLUG = "posthog-code"

# The registry slot stamphog's webhook carve-out reads its toggle resolver from; patched directly
# so the real review_hog resolver (registered at app-ready) never runs inside stamphog's tests.
_RESOLVER_SLOT = "products.stamphog.backend.facade.inbox_hooks._inbox_acting_reviewer_resolver"
# Deferred import inside the carve-out, so the defining module is the patch target.
_FIND_RUN = "products.tasks.backend.facade.api.find_signal_implementation_run"


def _signal_run_dto(team_id: int) -> SignalImplementationRunDTO:
    return SignalImplementationRunDTO(
        run_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        team_id=team_id,
        signal_report_id=uuid.uuid4(),
        task_created_by_id=None,
    )


def _pr_payload(
    *,
    action: str = "opened",
    installation_id: str = INSTALLATION_ID,
    repo: str = REPO,
    pr_number: int = 42,
    head_sha: str = "sha-1",
    head_branch: str = "feature-branch",
    head_repo: str | None = None,
    author_login: str = "member-dev",
    user_type: str = "User",
    author_association: str = "MEMBER",
    draft: bool = False,
    labels: list[str] | None = None,
    added_label: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    head: dict[str, Any] = {"sha": head_sha, "ref": head_branch}
    if head_repo is not None:
        head["repo"] = {"full_name": head_repo}
    pr: dict[str, Any] = {
        "number": pr_number,
        "html_url": f"https://github.com/{repo}/pull/{pr_number}",
        "head": head,
        "user": {"login": author_login, "type": user_type},
        "author_association": author_association,
        "draft": draft,
        "labels": [{"name": name} for name in labels or []],
    }
    if updated_at is not None:
        pr["updated_at"] = updated_at
    payload: dict[str, Any] = {
        "action": action,
        "installation": {"id": installation_id},
        "repository": {"full_name": repo},
        "pull_request": pr,
    }
    if added_label is not None:
        payload["label"] = {"name": added_label}
    return payload


def _run_task(
    payload: dict[str, Any], delivery_id: str, team_id: int, author_permission: str = "write", app_slug: str = APP_SLUG
):
    # transaction.on_commit never fires on its own outside a real commit, so run it
    # inline; execute_stamphog_review_workflow is a Temporal network call and gets mocked, as is
    # the author write-permission lookup (a GitHub API call). The App slug is set so the carve-out's
    # server-attested identity check can resolve <slug>[bot]; pass "" to exercise the fail-closed path.
    with (
        team_scope(team_id),
        override_instance_config("GITHUB_APP_SLUG", app_slug),
        patch("products.stamphog.backend.tasks.tasks.transaction.on_commit", side_effect=lambda fn, using=None: fn()),
        patch("products.stamphog.backend.tasks.tasks.execute_stamphog_review_workflow") as mock_execute,
        patch("products.stamphog.backend.tasks.tasks.StamphogGitHubClient") as mock_client,
    ):
        mock_client.return_value.get_collaborator_permission.return_value = author_permission
        process_pull_request_event(payload, delivery_id)
    return mock_execute


@pytest.fixture
def repo_config(team):
    with team_scope(team.id):
        return StamphogRepoConfig.objects.create(team_id=team.id, repository=REPO, installation_id=INSTALLATION_ID)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_queues_review_run_and_starts_workflow(team, repo_config):
    mock_execute = _run_task(_pr_payload(head_branch="feat/x"), "delivery-1", team.id)

    with team_scope(team.id):
        run = ReviewRun.objects.select_related("pull_request").get()
    assert run.status == ReviewRunStatus.QUEUED
    assert run.pull_request.pr_number == 42
    assert run.pull_request.head_branch == "feat/x"
    assert run.pull_request.repo_config_id == repo_config.id
    mock_execute.assert_called_once_with(review_run_id=str(run.id), team_id=team.id)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_duplicate_delivery_id_is_a_noop(team, repo_config):
    _run_task(_pr_payload(), "delivery-dup", team.id)
    mock_execute = _run_task(_pr_payload(), "delivery-dup", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 1
    mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "mutate_payload",
    [
        lambda p: {**p, "installation": {"id": "unknown"}},
        lambda p: {**p, "repository": {"full_name": "acme/other-repo"}},
        lambda p: {**p, "action": "closed"},
        lambda p: {**p, "pull_request": {}},
    ],
    ids=["unknown_installation", "unknown_repo", "irrelevant_action", "missing_pr_number"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_unmatched_events_create_no_review_run(team, repo_config, mutate_payload):
    payload = mutate_payload(_pr_payload())
    mock_execute = _run_task(payload, "delivery-noop", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "pr_kwargs,expect_run",
    [
        ({"draft": True}, False),
        ({"user_type": "Bot"}, False),
        ({"author_login": "renovate[bot]"}, False),
        ({"author_association": "NONE"}, False),
        ({"author_association": "CONTRIBUTOR"}, True),
        ({"author_association": "FIRST_TIME_CONTRIBUTOR"}, False),
        ({"author_association": "MEMBER"}, True),
    ],
    ids=[
        "draft",
        "bot_type",
        "bot_login",
        "none",
        "contributor_falls_through",
        "first_time_contributor",
        "member_proceeds",
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_review_path_skips_untrusted_bot_or_draft_prs(team, repo_config, pr_kwargs, expect_run):
    # Drafts, bot authors, and fork/external authors must be dropped before a sandbox is spent. The
    # fork/external drop is also a security boundary: an auto-approval must never satisfy required
    # reviews for a PR no trusted member opened. CONTRIBUTOR is NOT dropped at the payload gate — App
    # webhooks downgrade org members on private repos to CONTRIBUTOR, so it defers to the
    # write-permission gate (write here, via the harness default).
    mock_execute = _run_task(
        _pr_payload(**pr_kwargs), f"delivery-skip-{'-'.join(map(str, pr_kwargs.values()))}", team.id
    )

    with team_scope(team.id):
        count = ReviewRun.objects.count()
    if expect_run:
        assert count == 1
        mock_execute.assert_called_once()
    else:
        assert count == 0
        mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "author_permission,author_association,expect_run",
    [
        ("admin", "MEMBER", True),
        ("write", "MEMBER", True),
        ("read", "MEMBER", False),
        ("none", "MEMBER", False),
        ("write", "CONTRIBUTOR", True),
        ("read", "CONTRIBUTOR", False),
    ],
    ids=["admin", "write", "read_only", "no_access", "contributor_with_write", "contributor_read_only"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_review_path_requires_author_write_permission(
    team, repo_config, author_permission, author_association, expect_run
):
    # author_association alone can't prove push access (org MEMBERs and triage/read COLLABORATORs pass
    # it), so a trusted-association author below write must still be dropped before a run is queued.
    # The CONTRIBUTOR rows pin the payload-gate fall-through to this gate: a downgraded org member with
    # write gets reviewed, a genuine read-only contributor still never mints a run.
    mock_execute = _run_task(
        _pr_payload(author_association=author_association),
        f"delivery-perm-{author_permission}-{author_association}",
        team.id,
        author_permission,
    )

    with team_scope(team.id):
        count = ReviewRun.objects.count()
    if expect_run:
        assert count == 1
        mock_execute.assert_called_once()
    else:
        assert count == 0
        mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_author_permission_skip_retracts_stale_approvals_on_head_change(team, repo_config):
    # A synchronize skipped for lost write access must not leave a standing approval from an earlier
    # head satisfying required reviews — same hazard as the LABEL-mode skip.
    _run_task(_pr_payload(), "delivery-perm-approved", team.id)

    cache.clear()  # the first run cached the author's "write" permission; the revocation must be seen
    with patch("products.stamphog.backend.tasks.tasks.dismiss_stale_approvals_for_head", return_value=1) as dismiss:
        _run_task(_pr_payload(action="synchronize"), "delivery-perm-revoked", team.id, author_permission="read")

    dismiss.assert_called_once()
    with team_scope(team.id):
        assert ReviewRun.objects.count() == 1  # no second run was queued


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_disabled_repo_skip_retracts_stale_approvals_on_head_change(team, repo_config):
    # Disabling a repo opts out of reviews, but the standing approval from before the disable must
    # not keep satisfying required reviews over commits pushed after it.
    _run_task(_pr_payload(), "delivery-disabled-approved", team.id)
    with team_scope(team.id):
        StamphogRepoConfig.objects.filter(id=repo_config.id).update(enabled=False)

    with patch("products.stamphog.backend.tasks.tasks.dismiss_stale_approvals_for_head", return_value=1) as dismiss:
        mock_execute = _run_task(_pr_payload(action="synchronize"), "delivery-disabled-push", team.id)

    dismiss.assert_called_once()
    mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_untrusted_author_skip_retracts_stale_approvals_on_head_change(team, repo_config):
    # An author who loses their trusted association (left the org, collaborator removed) can still
    # push to an approved PR; the payload-only skip must retract the standing approval, not just
    # drop the event — otherwise the old approval keeps satisfying required reviews.
    _run_task(_pr_payload(), "delivery-assoc-approved", team.id)

    with patch("products.stamphog.backend.tasks.tasks.dismiss_stale_approvals_for_head", return_value=1) as dismiss:
        _run_task(_pr_payload(action="synchronize", author_association="NONE"), "delivery-assoc-revoked", team.id)

    dismiss.assert_called_once()
    with team_scope(team.id):
        assert ReviewRun.objects.count() == 1  # no second run was queued


@pytest.mark.parametrize(
    "review_mode,payload_kwargs,expect_run",
    [
        (ReviewMode.ALL, {"action": "labeled", "labels": ["stamphog"], "added_label": "stamphog"}, False),
        (ReviewMode.LABEL, {"action": "labeled", "labels": ["stamphog"], "added_label": "stamphog"}, True),
        (ReviewMode.LABEL, {"action": "labeled", "labels": ["stamphog", "bug"], "added_label": "bug"}, False),
        (ReviewMode.LABEL, {"action": "synchronize"}, False),
        (ReviewMode.LABEL, {"action": "synchronize", "labels": ["stamphog"]}, True),
    ],
    ids=[
        "all_mode_ignores_labeled",
        "label_mode_trigger_label_added_queues",
        "label_mode_other_label_added_skips",
        "label_mode_synchronize_without_label_skips",
        "label_mode_synchronize_with_label_queues",
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_review_mode_gates_events(team, repo_config, review_mode, payload_kwargs, expect_run):
    # LABEL mode is the Action-style opt-in: nothing runs unless the PR carries the trigger label, and
    # a `labeled` event only counts when the trigger label itself was just added. In ALL mode `labeled`
    # stays ignored — any label toggle would otherwise re-run the sandbox + LLM with no code change.
    with team_scope(team.id):
        repo_config.review_mode = review_mode
        repo_config.save()

    # Unique per case: the delivery-id dedup cache is process-global and would swallow a repeat.
    mock_execute = _run_task(_pr_payload(**payload_kwargs), f"delivery-mode-{uuid.uuid4()}", team.id)

    with team_scope(team.id):
        count = ReviewRun.objects.count()
    if expect_run:
        assert count == 1
        mock_execute.assert_called_once()
    else:
        assert count == 0
        mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_labeled_rereview_cooldown_skips_rapid_retrigger(team, repo_config):
    # Removing and re-adding the trigger label within the cooldown must not queue a second sandbox +
    # LLM run — the cheap re-review spam the cooldown exists for.
    with team_scope(team.id):
        repo_config.review_mode = ReviewMode.LABEL
        repo_config.save()

    payload = _pr_payload(action="labeled", labels=["stamphog"], added_label="stamphog")
    _run_task(payload, "delivery-label-1", team.id)
    mock_execute = _run_task(payload, "delivery-label-2", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 1
    mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_disabled_repo_config_is_a_noop(team, repo_config):
    with team_scope(team.id):
        repo_config.enabled = False
        repo_config.save()

    mock_execute = _run_task(_pr_payload(), "delivery-disabled", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "enabled,digest_enabled,expect_capture",
    [(False, True, True), (True, False, True), (False, False, False)],
    ids=["digest_only_captures", "review_only_captures", "fully_disabled_drops"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_merge_capture_gates_on_either_flag(team, repo_config, enabled, digest_enabled, expect_capture):
    # A merged PR must be captured whenever review OR digest is on — a digest-only repo (review off,
    # digest on) still needs its merges recorded or the daily digest has nothing to send. Only a fully
    # disabled repo drops the merge. Regression: the merge path used to gate on review `enabled` alone.
    with team_scope(team.id):
        repo_config.enabled = enabled
        repo_config.digest_enabled = digest_enabled
        repo_config.save()

    payload = _pr_payload(action="closed")
    payload["pull_request"]["merged"] = True
    payload["pull_request"]["merged_at"] = "2026-07-14T00:00:00Z"
    # Digest-eligible merges resolve their audience, which fetches the repo's declared digest
    # config from GitHub; stub the fetch as "file absent" (a transient error would now retry).
    with patch("products.stamphog.backend.logic.digest_config.StamphogGitHubClient") as digest_client_cls:
        digest_client_cls.return_value.get_default_branch_file.return_value = None
        _run_task(payload, f"delivery-merged-{enabled}-{digest_enabled}", team.id)

    with team_scope(team.id):
        captured = PullRequest.objects.filter(repo_config=repo_config, pr_number=42, merged_at__isnull=False).exists()
    assert captured is expect_capture


@pytest.mark.parametrize(
    "existing_status,expect_restart",
    [
        (ReviewRunStatus.QUEUED, True),
        (ReviewRunStatus.REVIEWING, False),
        (ReviewRunStatus.COMPLETED, False),
    ],
    ids=["queued_run_restarts", "reviewing_run_noop", "completed_run_noop"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_redelivery_restarts_only_a_still_queued_run(team, repo_config, existing_status, expect_restart):
    # A run committed by an earlier delivery whose workflow never started (Temporal was briefly down)
    # stays QUEUED. The redelivery/Celery-retry hits the unique delivery_id, and must restart that
    # run instead of logging "already processed" and silently dropping the PR. A run already past
    # QUEUED has a live/finished workflow, so its redelivery stays a plain no-op.
    with team_scope(team.id):
        pr_obj = PullRequest.objects.create(team_id=team.id, repo_config=repo_config, pr_number=42)
        ReviewRun.objects.create(
            team_id=team.id,
            pull_request=pr_obj,
            head_sha="sha-1",
            delivery_id="delivery-redelivered",
            status=existing_status,
        )

    mock_execute = _run_task(_pr_payload(head_sha="sha-1"), "delivery-redelivered", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 1  # no second run created for the duplicate delivery
        surviving = ReviewRun.objects.get()
        assert surviving.status == existing_status  # not superseded by its own redelivery
    if expect_restart:
        mock_execute.assert_called_once_with(review_run_id=str(surviving.id), team_id=team.id)
    else:
        mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_synchronize_supersedes_prior_non_terminal_run_but_not_terminal_ones(team, repo_config):
    _run_task(_pr_payload(action="opened", head_sha="sha-1"), "delivery-open", team.id)
    with team_scope(team.id):
        first_run = ReviewRun.objects.get()
        pull_request = PullRequest.objects.get(pr_number=42)
        completed_run = ReviewRun.objects.create(
            team_id=team.id,
            pull_request=pull_request,
            head_sha="sha-old",
            status=ReviewRunStatus.COMPLETED,
        )
        gated_run = ReviewRun.objects.create(
            team_id=team.id,
            pull_request=pull_request,
            head_sha="sha-older",
            status=ReviewRunStatus.GATED,
        )

    _run_task(_pr_payload(action="synchronize", head_sha="sha-2"), "delivery-sync", team.id)

    with team_scope(team.id):
        first_run.refresh_from_db()
        completed_run.refresh_from_db()
        gated_run.refresh_from_db()
        new_run = ReviewRun.objects.exclude(id__in=[first_run.id, completed_run.id, gated_run.id]).get()

    assert first_run.status == ReviewRunStatus.SUPERSEDED
    assert completed_run.status == ReviewRunStatus.COMPLETED
    assert gated_run.status == ReviewRunStatus.GATED  # a gate block is a completed outcome, not stale state
    assert new_run.status == ReviewRunStatus.QUEUED
    assert new_run.head_sha == "sha-2"


@pytest.mark.parametrize(
    "incoming_updated_at,expect_new_run",
    [
        ("2026-07-15T11:00:00Z", False),
        ("2026-07-15T12:00:00Z", True),
        ("2026-07-15T13:00:00Z", True),
    ],
    ids=["older_payload_skipped", "equal_payload_proceeds", "newer_payload_proceeds"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_out_of_order_payload_is_dropped(team, repo_config, incoming_updated_at, expect_new_run):
    # GitHub can deliver an older PR snapshot after a newer one. pull_request.updated_at is monotonic
    # per PR, so a strictly-older payload must be dropped — otherwise it supersedes the current run and
    # starts a stale review, leaving the PR unreviewed until the next push. Equal/newer proceed.
    with team_scope(team.id):
        PullRequest.objects.create(
            team_id=team.id,
            repo_config=repo_config,
            pr_number=42,
            payload_updated_at=parse_datetime("2026-07-15T12:00:00Z"),
        )

    mock_execute = _run_task(
        _pr_payload(action="synchronize", head_sha="sha-2", updated_at=incoming_updated_at),
        f"delivery-ooo-{uuid.uuid4()}",
        team.id,
    )

    with team_scope(team.id):
        count = ReviewRun.objects.count()
    if expect_new_run:
        assert count == 1
        mock_execute.assert_called_once()
    else:
        assert count == 0
        mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_stale_payload_recheck_under_lock_does_not_supersede_newer_run(team, repo_config):
    # Concurrency guard: two deliveries for the same PR can both pass the pre-transaction stale check,
    # then the older one wins the row lock second. _upsert_pull_request advances payload_updated_at
    # monotonically, so once it returns under the lock the stored value already reflects the newer
    # delivery. The older delivery must bail then — NOT supersede the up-to-date run and start a stale
    # review against an outdated head. Single-threaded the pre-guard would catch this first, so the race
    # is injected at the row-lock seam: _upsert_pull_request returns a row whose payload_updated_at has
    # already moved past the incoming payload, exactly what a concurrent commit leaves behind.
    with team_scope(team.id):
        pull_request = PullRequest.objects.create(
            team_id=team.id,
            repo_config=repo_config,
            pr_number=42,
            payload_updated_at=parse_datetime("2026-07-15T10:00:00Z"),  # old enough that the pre-guard passes
        )
        current_run = ReviewRun.objects.create(
            team_id=team.id, pull_request=pull_request, head_sha="sha-current", status=ReviewRunStatus.QUEUED
        )

    locked_pr = PullRequest.objects.for_team(team.id).get(id=pull_request.id)
    locked_pr.payload_updated_at = parse_datetime("2026-07-15T13:00:00Z")  # concurrent newer delivery already landed

    with patch("products.stamphog.backend.tasks.tasks._upsert_pull_request", return_value=locked_pr):
        mock_execute = _run_task(
            _pr_payload(action="synchronize", head_sha="sha-2", updated_at="2026-07-15T12:00:00Z"),
            f"delivery-race-{uuid.uuid4()}",
            team.id,
        )

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 1  # no new run created
        current_run.refresh_from_db()
    assert current_run.status == ReviewRunStatus.QUEUED  # the up-to-date run is left intact, not superseded
    mock_execute.assert_not_called()  # no workflow started for the stale delivery


@pytest.mark.parametrize(
    "has_base_change,expect_invalidated",
    [(True, True), (False, False)],
    ids=["base_retarget_invalidates_and_rereviews", "plain_edit_is_a_non_event"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_base_retarget_invalidates_same_head_approval(team, repo_config, has_base_change, expect_invalidated):
    # Retargeting the base rewrites the reviewed diff with the head SHA unchanged — post_verdict's
    # head guard and every head-keyed dismissal sweep are blind to it, so the standing approval and
    # any in-flight run must be invalidated explicitly and the PR re-reviewed. A plain title/body
    # edit stays a non-event.
    with team_scope(team.id):
        pull_request = PullRequest.objects.create(team_id=team.id, repo_config=repo_config, pr_number=42)
        in_flight = ReviewRun.objects.create(
            team_id=team.id, pull_request=pull_request, head_sha="sha-1", status=ReviewRunStatus.REVIEWING
        )
    payload = _pr_payload(action="edited", head_sha="sha-1")
    if has_base_change:
        payload["changes"] = {"base": {"ref": {"from": "master"}, "sha": {"from": "base-old"}}}

    with patch("products.stamphog.backend.tasks.tasks.dismiss_stale_approvals_for_head", return_value=1) as dismiss:
        mock_execute = _run_task(payload, f"delivery-retarget-{has_base_change}", team.id)

    with team_scope(team.id):
        in_flight.refresh_from_db()
        run_count = ReviewRun.objects.filter(pull_request=pull_request).count()
    if expect_invalidated:
        dismiss.assert_called_once()
        assert dismiss.call_args.args[3] == ""  # same-head exclusion disabled on purpose
        assert in_flight.status == ReviewRunStatus.SUPERSEDED
        assert run_count == 2  # the retargeted diff got a fresh run
        mock_execute.assert_called_once()
    else:
        dismiss.assert_not_called()
        assert in_flight.status == ReviewRunStatus.REVIEWING
        assert run_count == 1
        mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "incoming_updated_at,expect_refreshed",
    [
        ("2026-07-15T12:00:00Z", False),
        ("2026-07-15T14:00:00Z", True),
        ("2026-07-15T13:00:00Z", True),  # equal clock: a redelivery of the current snapshot may refresh
    ],
    ids=["older_snapshot_kept_out", "newer_snapshot_applied", "equal_snapshot_applied"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_upsert_pull_request_gates_metadata_on_payload_clock(
    team, repo_config, incoming_updated_at: str, expect_refreshed: bool
):
    # Out-of-order deliveries: an older snapshot reaching the upsert after a newer one committed
    # (both passed the pre-transaction stale guard) must not regress title/branch/body — they feed
    # API reads and digest summaries. The returned object must carry the winning clock either way,
    # because the caller's locked stale recheck compares against it.
    with team_scope(team.id):
        PullRequest.objects.create(
            team_id=team.id,
            repo_config=repo_config,
            pr_number=42,
            title="fresh title",
            head_branch="feat/fresh",
            body_excerpt="fresh body",
            payload_updated_at=parse_datetime("2026-07-15T13:00:00Z"),
        )
    incoming = {
        "number": 42,
        "title": "incoming title",
        "user": {"login": "someone"},
        "html_url": f"https://github.com/{REPO}/pull/42",
        "head": {"ref": "feat/incoming", "sha": "sha-incoming"},
        "body": "incoming body",
        "updated_at": incoming_updated_at,
    }

    with team_scope(team.id):
        pr_obj = _upsert_pull_request(repo_config, incoming)

    stored = PullRequest.objects.for_team(team.id).get(pr_number=42)
    expected_title = "incoming title" if expect_refreshed else "fresh title"
    expected_clock = parse_datetime(max(incoming_updated_at, "2026-07-15T13:00:00Z"))
    assert stored.title == expected_title
    assert stored.head_branch == ("feat/incoming" if expect_refreshed else "feat/fresh")
    assert stored.payload_updated_at == expected_clock
    assert pr_obj.payload_updated_at == expected_clock  # the locked recheck reads this off the returned object


def _installation_payload(
    *,
    action: str,
    installation_id: str = INSTALLATION_ID,
    added: list[str] | None = None,
    removed: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"action": action, "installation": {"id": installation_id}}
    if added is not None or removed is not None:
        payload["repositories_added"] = [{"full_name": name} for name in added or []]
        payload["repositories_removed"] = [{"full_name": name} for name in removed or []]
    return payload


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_installation_repos_added_creates_disabled_rows_and_skips_existing(team, repo_config):
    # A repo added to the installation after the initial sync must appear in the toggle list without a
    # manual re-sync — as a disabled row, since enabling reviews stays a human decision. An already
    # registered repo is left untouched (no duplicate, no settings reset).
    with team_scope(team.id):
        # Webhooks carry no PostHog identity, so the new row must inherit the connecting user
        # (the review-credential principal) from its synced sibling.
        StamphogRepoConfig.objects.filter(id=repo_config.id).update(connected_by_user_id=4242)
    payload = _installation_payload(action="added", added=["acme/new-repo", REPO])
    process_installation_event(payload, "delivery-inst-added")

    with team_scope(team.id):
        new_row = StamphogRepoConfig.objects.get(repository="acme/new-repo")
        assert new_row.enabled is False
        assert new_row.digest_enabled is False
        assert new_row.installation_id == INSTALLATION_ID
        assert new_row.connected_by_user_id == 4242
        repo_config.refresh_from_db()
        assert repo_config.enabled is True  # existing row untouched
        assert StamphogRepoConfig.objects.count() == 2


@pytest.mark.parametrize(
    "payload_kwargs,expect_disabled",
    [
        ({"action": "removed", "removed": [REPO]}, True),
        ({"action": "deleted"}, True),
        ({"action": "suspend"}, False),
    ],
    ids=["repo_removed_disables_row", "uninstall_disables_all_rows", "other_installation_action_ignored"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_installation_removal_tombstones_rows(team, repo_config, payload_kwargs, expect_disabled):
    # Removed repos and a full uninstall tombstone the configs (disabled, rows and history kept);
    # other installation actions are acked and ignored. In-flight runs must be superseded too —
    # workflows never re-check `enabled`, so a run already in the sandbox would otherwise still
    # post a verdict for a repo that left the installation. Terminal runs are history, kept as-is.
    with team_scope(team.id):
        repo_config.digest_enabled = True
        repo_config.save()
        pull_request = PullRequest.objects.create(
            team_id=team.id, repo_config=repo_config, pr_number=7, audience_key=""
        )
        in_flight = ReviewRun.objects.create(
            team_id=team.id, pull_request=pull_request, head_sha="sha-1", status=ReviewRunStatus.REVIEWING
        )
        terminal = ReviewRun.objects.create(
            team_id=team.id, pull_request=pull_request, head_sha="sha-0", status=ReviewRunStatus.COMPLETED
        )

    process_installation_event(_installation_payload(**payload_kwargs), f"delivery-inst-{payload_kwargs['action']}")

    with team_scope(team.id):
        repo_config.refresh_from_db()
        in_flight.refresh_from_db()
        terminal.refresh_from_db()
    assert repo_config.enabled is not expect_disabled
    assert repo_config.digest_enabled is not expect_disabled
    expected_in_flight = ReviewRunStatus.SUPERSEDED if expect_disabled else ReviewRunStatus.REVIEWING
    assert in_flight.status == expected_in_flight
    assert terminal.status == ReviewRunStatus.COMPLETED


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_installation_event_for_unbound_installation_is_a_noop(team, repo_config):
    # No config carries this installation yet, so there is no team to attribute rows to — the
    # user-driven sync flow binds it later.
    payload = _installation_payload(action="added", installation_id="9999", added=["acme/orphan-repo"])
    process_installation_event(payload, "delivery-inst-unbound")

    assert StamphogRepoConfig.objects.unscoped().filter(repository="acme/orphan-repo").exists() is False


def _make_second_team(organization) -> Team:
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=organization)
    return Team.objects.create(id=project.id, project=project, organization=organization)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_installation_uninstall_tombstones_every_owning_team(team, repo_config):
    # An installation's repos can be split across teams. An uninstall must tombstone all of them —
    # resolving to a single (oldest) team would leave the other team's rows live after the app is gone.
    second_team = _make_second_team(team.organization)
    with team_scope(second_team.id):
        second_config = StamphogRepoConfig.objects.create(
            team_id=second_team.id, repository="acme/other", installation_id=INSTALLATION_ID, digest_enabled=True
        )
    with team_scope(team.id):
        repo_config.digest_enabled = True
        repo_config.save()

    process_installation_event(_installation_payload(action="deleted"), "delivery-multi-uninstall")

    with team_scope(team.id):
        repo_config.refresh_from_db()
    with team_scope(second_team.id):
        second_config.refresh_from_db()
    assert (repo_config.enabled, repo_config.digest_enabled) == (False, False)
    assert (second_config.enabled, second_config.digest_enabled) == (False, False)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_installation_repos_added_skips_when_installation_spans_multiple_teams(team, repo_config):
    # Ambiguous ownership: two teams share the installation, so auto-binding a newly added repo could
    # attach it to a team its adder never intended. The webhook add is skipped and left to the
    # authenticated sync flow — no row is created for either team.
    second_team = _make_second_team(team.organization)
    with team_scope(second_team.id):
        StamphogRepoConfig.objects.create(
            team_id=second_team.id, repository="acme/other", installation_id=INSTALLATION_ID
        )

    payload = _installation_payload(action="added", added=["acme/brand-new"])
    process_installation_event(payload, "delivery-multi-add")

    assert StamphogRepoConfig.objects.unscoped().filter(repository="acme/brand-new").exists() is False


def _selfdriving_payload(**overrides: Any) -> dict[str, Any]:
    """A synchronize delivery shaped like a self-driving inbox PR: bot-authored draft, repo-native branch."""
    kwargs: dict[str, Any] = {
        "action": "synchronize",
        "head_sha": "sha-2",
        "head_repo": REPO,
        "author_login": "posthog-code[bot]",
        "user_type": "Bot",
        "author_association": "NONE",
        "draft": True,
        **overrides,
    }
    return _pr_payload(**kwargs)


def _sync_repo_config(team_id: int, repo_config: StamphogRepoConfig) -> None:
    # The carve-out requires a synced config (connecting user present); the fixture row has none.
    with team_scope(team_id):
        StamphogRepoConfig.objects.filter(id=repo_config.id).update(connected_by_user_id=4242)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_carve_out_rereviews_a_selfdriving_pr_past_every_gate(team, repo_config):
    # The whole carve-out in one delivery: a bot-authored DRAFT PR on a LABEL-mode repo with no
    # trigger label, whose author has no write permission — every pre-filter and gate would drop it —
    # still queues a re-review with inbox provenance stamped, because it is positively task-linked
    # and the acting reviewer's toggle is on. Any one gate accidentally re-applied breaks this.
    _sync_repo_config(team.id, repo_config)
    with team_scope(team.id):
        StamphogRepoConfig.objects.filter(id=repo_config.id).update(review_mode=ReviewMode.LABEL)

    dto = _signal_run_dto(team.id)
    with (
        patch(_FIND_RUN, return_value=dto) as mock_find,
        patch(_RESOLVER_SLOT, lambda team_id, report_id, created_by: 777),
    ):
        mock_execute = _run_task(_selfdriving_payload(), "delivery-inbox-sync", team.id, author_permission="read")

    with team_scope(team.id):
        run = ReviewRun.objects.select_related("pull_request").get()
    assert run.status == ReviewRunStatus.QUEUED
    assert run.head_sha == "sha-2"
    assert run.output["inbox_review"] == {
        "trigger": "webhook",
        "signal_report_id": str(dto.signal_report_id),
        "task_run_id": str(dto.run_id),
        "acting_user_id": 777,
    }
    mock_execute.assert_called_once_with(review_run_id=str(run.id), team_id=team.id)
    # Fork-safety feeds the lookup the base repo and both PR locators; the config's team scopes it.
    mock_find.assert_called_once_with(
        team_id=team.id, repository=REPO, pr_url=f"https://github.com/{REPO}/pull/42", head_branch="feature-branch"
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_carve_out_toggle_off_still_dismisses_stale_approvals(team, repo_config):
    # Decision: dismissal is never preference-gated. A synchronize on a task-linked PR whose acting
    # reviewer switched the toggle off must not re-review, but the standing approval from the earlier
    # head must still be retracted — otherwise it keeps satisfying required reviews over new commits.
    _sync_repo_config(team.id, repo_config)
    with (
        patch(_FIND_RUN, return_value=_signal_run_dto(team.id)),
        patch(_RESOLVER_SLOT, lambda team_id, report_id, created_by: None),
        patch("products.stamphog.backend.tasks.tasks.dismiss_stale_approvals_for_head", return_value=1) as dismiss,
    ):
        mock_execute = _run_task(_selfdriving_payload(), "delivery-inbox-off", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()
    dismiss.assert_not_called()  # no PullRequest row exists yet, so there is nothing to dismiss...

    # ...but with a prior run on record the retraction must fire.
    with team_scope(team.id):
        pr_obj = PullRequest.objects.create(team_id=team.id, repo_config=repo_config, pr_number=42)
        ReviewRun.objects.create(team_id=team.id, pull_request=pr_obj, head_sha="sha-1", posted_review_id=9)
    with (
        patch(_FIND_RUN, return_value=_signal_run_dto(team.id)),
        patch(_RESOLVER_SLOT, lambda team_id, report_id, created_by: None),
        patch("products.stamphog.backend.tasks.tasks.dismiss_stale_approvals_for_head", return_value=1) as dismiss,
    ):
        mock_execute = _run_task(_selfdriving_payload(), "delivery-inbox-off-2", team.id)

    dismiss.assert_called_once()
    # The copy must say why (nobody is opted in), not the generic no-longer-qualifies message.
    assert dismiss.call_args.kwargs["message"] == _INBOX_OPT_OUT_DISMISS_MESSAGE
    mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "carve_kwargs,find_result_team_delta,resolver,expect_run",
    [
        ({}, 0, 777, True),
        ({"head_repo": "fork/widgets"}, 0, 777, False),
        ({"author_login": "dependabot[bot]"}, 0, 777, False),
        ({"action": "opened"}, 0, 777, False),
        ({"action": "ready_for_review", "draft": False}, 0, 777, False),
        ({}, 1, 777, False),
        ({}, 0, None, False),
    ],
    ids=[
        "synchronize_rereviews",
        "fork_head_is_never_linked",
        "foreign_bot_is_never_linked",
        "opened_is_the_receiver_legs_job",
        "ready_for_review_keeps_the_draft_verdict",
        "team_mismatch_fails_closed",
        "no_registered_resolver_fails_closed",
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_carve_out_scope(team, repo_config, carve_kwargs, find_result_team_delta, resolver, expect_run):
    # The carve-out must stay exactly as narrow as decided: later head-changing deliveries only
    # (opened belongs to the receiver leg; ready_for_review keeps the draft-time verdict), never for
    # fork heads, never across teams, and fail-closed when review_hog isn't there to answer the
    # toggle question. Everything else keeps today's bot-author skip.
    _sync_repo_config(team.id, repo_config)
    dto = _signal_run_dto(team.id + find_result_team_delta)
    resolver_fn = (lambda team_id, report_id, created_by: resolver) if resolver is not None else None
    with (
        patch(_FIND_RUN, return_value=dto),
        patch(_RESOLVER_SLOT, resolver_fn),
    ):
        mock_execute = _run_task(_selfdriving_payload(**carve_kwargs), f"delivery-scope-{uuid.uuid4()}", team.id)

    with team_scope(team.id):
        count = ReviewRun.objects.count()
    if expect_run:
        assert count == 1
        mock_execute.assert_called_once()
    else:
        assert count == 0
        mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_carve_out_requires_task_linkage(team, repo_config):
    # A bot-authored PR with no matching implementation run (dependabot, a wizard/manual PostHog Code
    # PR) must keep today's behavior byte-for-byte: skipped, no run, no review.
    _sync_repo_config(team.id, repo_config)
    with (
        patch(_FIND_RUN, return_value=None),
        patch(_RESOLVER_SLOT, lambda team_id, report_id, created_by: 777),
    ):
        mock_execute = _run_task(_selfdriving_payload(), "delivery-inbox-unlinked", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()


def _run_inbox_task(
    team_id: int,
    pr: dict[str, Any] | None,
    pr_url: str = f"https://github.com/{REPO}/pull/42",
    app_slug: str = APP_SLUG,
):
    """Run process_inbox_pr_review with GitHub and Temporal mocked; returns (mock_execute, mock_client)."""
    with (
        team_scope(team_id),
        override_instance_config("GITHUB_APP_SLUG", app_slug),
        patch("products.stamphog.backend.tasks.tasks.transaction.on_commit", side_effect=lambda fn, using=None: fn()),
        patch("products.stamphog.backend.tasks.tasks.execute_stamphog_review_workflow") as mock_execute,
        patch("products.stamphog.backend.tasks.tasks.StamphogGitHubClient") as mock_client,
    ):
        mock_client.return_value.get_pr.return_value = pr
        process_inbox_pr_review(
            team_id=team_id,
            pr_url=pr_url,
            acting_user_id=777,
            signal_report_id="report-1",
            task_run_id="run-1",
        )
    return mock_execute, mock_client


def _inbox_pr(
    state: str = "open",
    head_sha: str = "sha-1",
    author_login: str = "posthog-code[bot]",
    user_type: str = "Bot",
    head_repo: str = REPO,
) -> dict[str, Any]:
    """The REST get_pr shape the receiver-leg task consumes (no webhook payload on this leg).

    A real get_pr response carries head.repo.full_name, which the server-attested identity check
    needs; defaults describe a genuine self-driving PR (App bot author, repo-native head).
    """
    return {
        "number": 42,
        "state": state,
        "html_url": f"https://github.com/{REPO}/pull/42",
        "title": "feat: self-driving fix",
        "user": {"login": author_login, "type": user_type},
        "draft": True,
        "head": {"sha": head_sha, "ref": "posthog-code/fix", "repo": {"full_name": head_repo}},
        "updated_at": "2026-07-20T00:00:00Z",
    }


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_receiver_leg_reviews_the_draft_pr(team, repo_config):
    # The receiver leg's spine: a synced+enabled config + an open (draft, bot-authored) PR fetched
    # from GitHub -> PullRequest upserted, run created with inbox provenance (what flips the engine's
    # self-driving carve-out), workflow started. Without the provenance the engine refuses the bot
    # author and the whole feature silently never reviews anything.
    _sync_repo_config(team.id, repo_config)
    mock_execute, _ = _run_inbox_task(team.id, _inbox_pr())

    with team_scope(team.id):
        run = ReviewRun.objects.select_related("pull_request").get()
    assert run.status == ReviewRunStatus.QUEUED
    assert run.head_sha == "sha-1"
    assert run.delivery_id is None
    assert run.pull_request.pr_number == 42
    assert run.output["inbox_review"] == {
        "trigger": "inbox",
        "signal_report_id": "report-1",
        "task_run_id": "run-1",
        "acting_user_id": 777,
    }
    mock_execute.assert_called_once_with(review_run_id=str(run.id), team_id=team.id)


@pytest.mark.parametrize(
    "config_mutation",
    [
        lambda c: c.update(enabled=False),
        lambda c: c.update(installation_id=""),
        lambda c: c.update(connected_by_user_id=None),
        lambda c: c.update(repository="acme/other-repo"),
    ],
    ids=["disabled", "never_synced", "no_connecting_user", "different_repo"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_receiver_leg_noops_without_a_reviewable_config(team, repo_config, config_mutation):
    # Self-scoping (decision): toggle on without a synced+enabled config covering the PR's repository
    # is a silent no-op — no GitHub fetch, no run — so the toggle is inert for teams that never
    # installed the Stamphog App, and a disabled/unsynced repo can't be reviewed through the side door.
    _sync_repo_config(team.id, repo_config)
    with team_scope(team.id):
        config_mutation(StamphogRepoConfig.objects.filter(id=repo_config.id))

    mock_execute, mock_client = _run_inbox_task(team.id, _inbox_pr())

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()
    mock_client.return_value.get_pr.assert_not_called()


@pytest.mark.parametrize(
    "existing_status,fetched_head,expect_started,expected_runs",
    [
        (ReviewRunStatus.QUEUED, "sha-1", "existing", 1),
        (ReviewRunStatus.COMPLETED, "sha-1", None, 1),
        (ReviewRunStatus.FAILED, "sha-1", "new", 2),
        (ReviewRunStatus.COMPLETED, "sha-2", "new", 2),
        (ReviewRunStatus.QUEUED, "sha-2", "new", 2),
    ],
    ids=[
        "stranded_queued_run_restarts",
        "completed_run_noop",
        "failed_run_recreated_on_refire",
        "missed_webhook_head_gets_reviewed",
        "stale_queued_run_superseded_for_new_head",
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_receiver_leg_refires_dedupe_on_the_current_head(
    team, repo_config, existing_status, fetched_head, expect_started, expected_runs
):
    # The TaskRun receiver re-fires on every output save carrying the PR URL. At an already-handled
    # head it must not mint a second run (and a second sandbox) per save — except a still-QUEUED run
    # whose post-commit workflow start failed, which gets restarted instead of stranded. A FAILED
    # run doesn't count as handled: the refire recreates it, so a single-commit PR whose one review
    # died isn't permanently stranded without a verdict. At a head the webhook leg never delivered
    # (a lost synchronize), the refire is the only path left that reviews the new commits, so it
    # must supersede and create.
    _sync_repo_config(team.id, repo_config)
    with team_scope(team.id):
        pr_obj = PullRequest.objects.create(team_id=team.id, repo_config=repo_config, pr_number=42)
        existing = ReviewRun.objects.create(
            team_id=team.id, pull_request=pr_obj, head_sha="sha-1", status=existing_status
        )

    mock_execute, _ = _run_inbox_task(team.id, _inbox_pr(head_sha=fetched_head))

    with team_scope(team.id):
        assert ReviewRun.objects.count() == expected_runs
        if expect_started == "existing":
            mock_execute.assert_called_once_with(review_run_id=str(existing.id), team_id=team.id)
        elif expect_started == "new":
            new_run = ReviewRun.objects.exclude(id=existing.id).get()
            assert new_run.head_sha == fetched_head
            mock_execute.assert_called_once_with(review_run_id=str(new_run.id), team_id=team.id)
        else:
            mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_receiver_leg_stale_fetch_does_not_supersede_a_newer_run(team, repo_config):
    # Race: the receiver's REST fetch returns a pre-push snapshot while the push's synchronize
    # delivery already committed a run at the new head. Without the payload-clock recheck the
    # older snapshot would supersede that run and re-review the outdated head.
    _sync_repo_config(team.id, repo_config)
    with team_scope(team.id):
        pr_obj = PullRequest.objects.create(
            team_id=team.id,
            repo_config=repo_config,
            pr_number=42,
            payload_updated_at=parse_datetime("2026-07-21T00:00:00Z"),
        )
        newer = ReviewRun.objects.create(
            team_id=team.id, pull_request=pr_obj, head_sha="sha-2", status=ReviewRunStatus.QUEUED
        )

    # _inbox_pr's updated_at (2026-07-20) is older than the stored payload clock.
    mock_execute, _ = _run_inbox_task(team.id, _inbox_pr(head_sha="sha-1"))

    with team_scope(team.id):
        newer.refresh_from_db()
        assert newer.status == ReviewRunStatus.QUEUED
        assert ReviewRun.objects.count() == 1
    mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_receiver_leg_skips_a_closed_pr(team, repo_config):
    # A late output save can re-fire the receiver long after the PR closed or merged; reviewing a
    # closed PR burns a sandbox to post a verdict nobody can act on.
    _sync_repo_config(team.id, repo_config)
    mock_execute, _ = _run_inbox_task(team.id, _inbox_pr(state="closed"))

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "pr_kwargs,app_slug",
    [
        ({"author_login": "dependabot[bot]", "user_type": "Bot"}, APP_SLUG),
        ({"head_repo": "fork/widgets"}, APP_SLUG),
        ({"author_login": "human-dev", "user_type": "User"}, APP_SLUG),
        ({}, ""),
    ],
    ids=["foreign_bot", "fork_head", "human_author", "app_slug_unconfigured"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_inbox_receiver_leg_refuses_non_self_driving_prs(team, repo_config, pr_kwargs, app_slug):
    # output.pr_url is caller-writable, so the receiver re-verifies server-attested identity before
    # stamping inbox provenance: a foreign bot, a fork head, a human author, or an instance with no
    # App slug configured must never mint an inbox-provenance run (the stamp that flips the engine's
    # bot/draft bypass). Guards the escalation where a member points a signal-report run at an
    # arbitrary open PR in a configured repo to win an approve-first review past every gate.
    _sync_repo_config(team.id, repo_config)
    mock_execute, _ = _run_inbox_task(team.id, _inbox_pr(**pr_kwargs), app_slug=app_slug)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()
