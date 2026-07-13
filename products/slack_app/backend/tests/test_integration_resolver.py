import pytest

from django.apps import apps
from django.test import override_settings
from django.utils import timezone

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping, SlackUserProfileCache
from products.slack_app.backend.services.integration_resolver import load_integrations, resolve_user_for_workspace

WORKSPACE = "T_WS"
SLACK_USER = "U001"


class TestResolveIntegration:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        from django.core.cache import cache

        from products.slack_app.backend.services.slack_auth import write_auth_state_ok

        cache.clear()
        self.organization = Organization.objects.create(name="Org")
        self.team_a = Team.objects.create(organization=self.organization, name="A")
        self.team_b = Team.objects.create(organization=self.organization, name="B")
        # team_c lives in a separate org the user has no membership in.
        self.other_org = Organization.objects.create(name="Other")
        self.team_c = Team.objects.create(organization=self.other_org, name="C")

        self.user = User.objects.create(email="dev@example.com", distinct_id="u-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

        self.integration_a = self._mk_integration(self.team_a)
        self.integration_b = self._mk_integration(self.team_b)
        self.integration_c = self._mk_integration(self.team_c)
        # Different workspace; should never match the WORKSPACE-scoped lookups.
        self.integration_other_workspace = Integration.objects.create(
            team=self.team_a,
            kind="slack",
            integration_id="T_OTHER",
            sensitive_config={"access_token": "xoxb-other"},
        )
        # These tests assert routing precedence (thread > user_default > etc),
        # not auth-state filtering. Pre-seed every WORKSPACE-scoped integration
        # as healthy so ``load_integrations``' eager ``auth.test`` short-circuits
        # on cache hit and the precedence ladder is exercised against a stable
        # full candidate list. ``integration_other_workspace`` is intentionally
        # not seeded — it has a different ``integration_id`` and never enters
        # the candidate set.
        for integration in (self.integration_a, self.integration_b, self.integration_c):
            write_auth_state_ok(integration.id, bot_user_id="U_BOT")
        yield
        cache.clear()

    def _mk_integration(self, team: Team) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="slack",
            integration_id=WORKSPACE,
            sensitive_config={"access_token": "xoxb"},
        )

    def _workspace_integrations(self) -> list[Integration]:
        return list(
            Integration.objects.filter(kind="slack", integration_id=WORKSPACE).select_related(
                "team", "team__organization"
            )
        )

    def _mk_thread_mapping(
        self,
        *,
        team: Team,
        integration: Integration,
        channel: str = "C1",
        thread_ts: str = "123.456",
    ) -> SlackThreadTaskMapping:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(team=team, title="t")
        task_run = TaskRun.objects.create(team=team, task=task)
        return SlackThreadTaskMapping.objects.create(
            team=team,
            integration=integration,
            slack_workspace_id=WORKSPACE,
            channel=channel,
            thread_ts=thread_ts,
            task=task,
            task_run=task_run,
            mentioning_slack_user_id=SLACK_USER,
        )

    def test_thread_mapping_wins_over_everything(self):
        self._mk_thread_mapping(team=self.team_b, integration=self.integration_b)
        # Even with an unrelated user_default pointing at A, the thread mapping wins.
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
            channel="C1",
            thread_ts="123.456",
        )

        assert result.source == "thread"
        assert result.integration == self.integration_b

    def test_thread_mapping_ignored_when_user_lacks_access(self):
        # Thread mapping targets team_c, which the user has no membership in
        # (it's in `other_org`). The thread match must be skipped — a user
        # whose access was revoked or who never had access can't drive the
        # thread just by replying to it.
        self._mk_thread_mapping(team=self.team_c, integration=self.integration_c)

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
            channel="C1",
            thread_ts="123.456",
        )

        # Falls through past the thread match to the picker over the user's
        # accessible candidates (A, B).
        assert result.source == "needs_picker"
        assert {i.id for i in result.candidates} == {self.integration_a.id, self.integration_b.id}

    def test_thread_mapping_remaps_to_sibling_when_mapped_integration_out_of_lookup(self):
        # Older mapping points at a sibling Integration row of a different kind
        # for the same team in this workspace. The resolver must remap to the
        # in-set sibling and keep the mapping's task_run linkage rather than
        # fall back to the picker.
        legacy_integration = Integration.objects.create(
            team=self.team_b,
            kind="slack-posthog-code",
            integration_id=WORKSPACE,
            sensitive_config={"access_token": "xoxb-legacy"},
        )
        self._mk_thread_mapping(team=self.team_b, integration=legacy_integration)

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
            channel="C1",
            thread_ts="123.456",
        )

        assert result.source == "thread"
        assert result.integration == self.integration_b

    def test_thread_mapping_falls_through_when_no_sibling_for_team(self):
        # The mapping points at an Integration whose team has no candidate in
        # the current lookup at all (kind drift left no replacement). Without a
        # sibling to remap to, the resolver must fall through to the next
        # branch rather than route to a row that isn't in the candidate set.
        self.integration_b.delete()
        legacy_integration = Integration.objects.create(
            team=self.team_b,
            kind="slack-posthog-code",
            integration_id=WORKSPACE,
            sensitive_config={"access_token": "xoxb-legacy"},
        )
        self._mk_thread_mapping(team=self.team_b, integration=legacy_integration)

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
            channel="C1",
            thread_ts="123.456",
        )

        # Only integration_a remains accessible → resolves as sole candidate.
        assert result.source == "sole_candidate"
        assert result.integration == self.integration_a

    def test_user_default_used_when_accessible(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "user_default"
        assert result.integration == self.integration_a

    def test_user_default_ignored_when_target_no_longer_accessible(self):
        # Default points at team_c, which the user has no membership in.
        SlackSettings.objects.create(
            default_integration=self.integration_c,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        # Falls through past user_default: A and B remain accessible → picker.
        assert result.source == "needs_picker"
        assert {i.id for i in result.candidates} == {self.integration_a.id, self.integration_b.id}

    def test_user_default_ignored_when_target_kind_changed(self):
        # Stored default points at integration_a, but its kind no longer matches the
        # Slack lookup (e.g. the row was repurposed for a different provider). The
        # default must silently fall through rather than routing the user to the
        # wrong-kind integration.
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )
        self.integration_a.kind = "github"
        self.integration_a.save(update_fields=["kind"])

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        # integration_a is no longer in the candidate set (kind filter excludes
        # it), so the stale default is ignored. integration_b is the sole
        # remaining accessible candidate.
        assert result.source == "sole_candidate"
        assert result.integration == self.integration_b

    def test_null_user_default_falls_through_to_workspace(self):
        # A null personal row exists because the user reset their project
        # routing back to workspace default. The resolver must skip it and
        # use the workspace-wide row.
        SlackSettings.objects.create(
            default_integration=None,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=None,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "workspace_default"
        assert result.integration == self.integration_a

    def test_user_default_wins_over_workspace_default(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=None,  # workspace-wide
        )
        SlackSettings.objects.create(
            default_integration=self.integration_b,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "user_default"
        assert result.integration == self.integration_b

    def test_workspace_default_used_when_no_user_row(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=None,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "workspace_default"
        assert result.integration == self.integration_a

    def test_workspace_default_ignored_when_target_not_accessible(self):
        # Workspace default points at team_c — the user has no access.
        SlackSettings.objects.create(
            default_integration=self.integration_c,
            slack_workspace_id=WORKSPACE,
            slack_user_id=None,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        # Falls through to candidate selection.
        assert result.source == "needs_picker"
        assert {i.id for i in result.candidates} == {self.integration_a.id, self.integration_b.id}

    def test_sole_candidate_auto_used(self):
        # Remove integration B so only A is accessible to the user in this workspace.
        self.integration_b.delete()

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "sole_candidate"
        assert result.integration == self.integration_a

    def test_picker_with_multiple_candidates(self):
        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.integration is None
        assert result.source == "needs_picker"
        assert {i.id for i in result.candidates} == {self.integration_a.id, self.integration_b.id}

    def test_unresolved_user_falls_back_to_full_candidates(self):
        # user=None is the webhook routing layer's call: skip accessibility filtering
        # and trust saved routing rows. Without any defaults, every workspace
        # integration becomes a candidate.
        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=None,
        )

        assert result.integration is None
        assert result.source == "needs_picker"
        assert {i.id for i in result.candidates} == {
            self.integration_a.id,
            self.integration_b.id,
            self.integration_c.id,
        }

    def test_unresolved_user_still_honors_user_default(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=None,
        )

        assert result.source == "user_default"
        assert result.integration == self.integration_a

    def test_unresolved_user_still_honors_thread_mapping(self):
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")

        task = Task.objects.create(team=self.team_b, title="t")
        task_run = TaskRun.objects.create(team=self.team_b, task=task)
        SlackThreadTaskMapping.objects.create(
            team=self.team_b,
            integration=self.integration_b,
            slack_workspace_id=WORKSPACE,
            channel="C1",
            thread_ts="123.456",
            task=task,
            task_run=task_run,
            mentioning_slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=None,
            channel="C1",
            thread_ts="123.456",
        )

        assert result.source == "thread"
        assert result.integration == self.integration_b

    def test_unresolved_user_trusts_inaccessible_default(self):
        # team_c is in another org. With user=None we don't check accessibility, so
        # the saved default still wins. The workflow's user-resolution will reject
        # the event downstream if needed.
        SlackSettings.objects.create(
            default_integration=self.integration_c,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=None,
        )

        assert result.source == "user_default"
        assert result.integration == self.integration_c

    def test_other_workspace_integrations_are_excluded(self):
        # Delete integration_b so only integration_a in WORKSPACE remains accessible —
        # verifies the unrelated T_OTHER integration is filtered out by workspace.
        self.integration_b.delete()

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "sole_candidate"
        assert result.integration == self.integration_a

    @override_settings(DEBUG=True)
    def test_debug_workspace_user_resolution_uses_seeded_local_user(self):
        local_user = User.objects.create(email="test@posthog.com", distinct_id="u-local")
        OrganizationMembership.objects.create(user=local_user, organization=self.organization)
        SlackUserProfileCache.objects.create(
            integration=self.integration_a,
            slack_user_id=SLACK_USER,
            email="chris.v@posthog.com",
            refreshed_at=timezone.now(),
        )
        workspace_result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            user=None,
        )

        result = resolve_user_for_workspace(
            workspace_result=workspace_result,
            slack_team_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        assert result.user == local_user
        assert result.failure_reason is None
        assert {c.id for c in result.candidates} == {self.integration_a.id, self.integration_b.id}


class TestLoadIntegrationsAuthStateFilter:
    """Covers the eager auth-check + cache-driven ordering in ``load_integrations``.

    Scenario mirrors a real customer case: an org has three Slack rows for the
    same workspace, one of them has a revoked bot token, the resolver used to
    pick that one as ``candidates[0]`` and silently broke every mention. The
    consolidated ``check_integrations_auth_and_filter`` ranks the healthy ones
    first so the dead probe never makes it to index 0.
    """

    @pytest.fixture(autouse=True)
    def _bypass_slack_auth_filter(self):
        """Override the conftest's auto-bypass so this class exercises the real
        filter — that's the whole point of the class."""
        yield

    @pytest.fixture(autouse=True)
    def setup(self, db):
        from unittest.mock import MagicMock, patch

        from django.core.cache import cache

        cache.clear()
        self.organization = Organization.objects.create(name="Org")
        self.team_old = Team.objects.create(organization=self.organization, name="Old")
        self.team_mid = Team.objects.create(organization=self.organization, name="Mid")
        self.team_new = Team.objects.create(organization=self.organization, name="New")
        # Order rows by creation so the PK ascending order matches the team
        # names; downstream assertions rely on this implicit ordering.
        self.integration_old = self._mk_integration(self.team_old)
        self.integration_mid = self._mk_integration(self.team_mid)
        self.integration_new = self._mk_integration(self.team_new)
        # Mock ``auth.test`` to a healthy response by default; individual tests
        # override ``side_effect`` / ``return_value`` to simulate the failure
        # they care about. Without the mock, ``load_integrations`` would try
        # to hit the real Slack API every time the cache is cold. Context
        # manager so a failure inside ``yield`` still cleans up (manual
        # ``start()/stop()`` would leak the patch into sibling tests).
        with patch("posthog.models.integration.WebClient") as mock_webclient_class:
            mock_client = MagicMock()
            mock_webclient_class.return_value = mock_client
            mock_client.auth_test.return_value = {"user_id": "U_BOT"}
            self.mock_auth_test = mock_client.auth_test
            yield
        cache.clear()

    def _mk_integration(self, team: Team) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="slack",
            integration_id=WORKSPACE,
            sensitive_config={"access_token": "xoxb"},
        )

    def _candidate_ids(self, result_candidates: list[Integration]) -> list[int]:
        return [c.id for c in result_candidates]

    def test_cold_cache_runs_auth_test_per_candidate_and_caches_verdict(self):
        from products.slack_app.backend.services.slack_auth import get_cached_auth_state

        result = load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)

        # auth.test fired once per candidate — eager populate is the point of
        # the new design.
        assert self.mock_auth_test.call_count == 3
        # All three are returned (just possibly in different timestamp order).
        assert {c.id for c in result.candidates} == {
            self.integration_old.id,
            self.integration_mid.id,
            self.integration_new.id,
        }
        # Cache now carries a healthy verdict for each, including the bot user id.
        for integration in (self.integration_old, self.integration_mid, self.integration_new):
            state = get_cached_auth_state(integration.id)
            assert state is not None
            assert state.ok is True
            assert state.bot_user_id == "U_BOT"

    def test_warm_cache_skips_auth_test(self):
        from products.slack_app.backend.services.slack_auth import write_auth_state_ok

        write_auth_state_ok(self.integration_old.id, bot_user_id="U_BOT")
        write_auth_state_ok(self.integration_mid.id, bot_user_id="U_BOT")
        write_auth_state_ok(self.integration_new.id, bot_user_id="U_BOT")

        load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)

        assert self.mock_auth_test.call_count == 0

    def test_invalid_auth_drops_install_from_candidates(self):
        from slack_sdk.errors import SlackApiError

        # ``old`` install fails auth.test with invalid_auth — exactly the
        # production case for the original ticket. ``mid`` and ``new`` succeed
        # so the resolver should keep them and drop ``old`` entirely (not
        # demote to the back, otherwise the resolver's precedence ladder would
        # still pin a stale thread mapping or user-default to it).
        healthy_response = {"user_id": "U_BOT"}
        self.mock_auth_test.side_effect = [
            SlackApiError("invalid_auth", response={"ok": False, "error": "invalid_auth"}),
            healthy_response,
            healthy_response,
        ]

        result = load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)

        ids = self._candidate_ids(result.candidates)
        assert self.integration_old.id not in ids
        assert set(ids) == {self.integration_mid.id, self.integration_new.id}

    def test_freshest_healthy_wins_over_warm_older_entry(self):
        # ``new`` was confirmed healthy most recently; ``old`` and ``mid``
        # were checked an hour ago. Matches the "customer just reconnected
        # one of three installs" scenario.
        from datetime import timedelta

        from django.core.cache import cache as django_cache
        from django.utils import timezone

        from products.slack_app.backend.services.slack_auth import (
            SLACK_AUTH_STATE_CACHE_TTL_SECONDS,
            SlackIntegrationAuthState,
            _cache_key,
        )

        an_hour_ago = timezone.now() - timedelta(hours=1)
        for integration in (self.integration_old, self.integration_mid):
            django_cache.set(
                _cache_key(integration.id),
                SlackIntegrationAuthState(ok=True, bot_user_id="U_BOT", error_code=None, checked_at=an_hour_ago),
                timeout=SLACK_AUTH_STATE_CACHE_TTL_SECONDS,
            )
        django_cache.set(
            _cache_key(self.integration_new.id),
            SlackIntegrationAuthState(ok=True, bot_user_id="U_BOT", error_code=None, checked_at=timezone.now()),
            timeout=SLACK_AUTH_STATE_CACHE_TTL_SECONDS,
        )

        result = load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)

        assert result.candidates[0].id == self.integration_new.id
        assert self.mock_auth_test.call_count == 0  # all cached, no API calls

    def test_all_broken_returns_empty(self):
        # When every candidate is cached as broken, return an empty list.
        # Upstream code (``resolve_region_or_terminal_route``) treats an empty
        # candidate set the same way it'd handle a workspace with no rows at
        # all — falls through to ``ROUTE_NO_INTEGRATION``. Recovery paths:
        # the 6h TTL expires, OAuth reconnect invalidates the cache, or a
        # subsequent ``auth.test`` succeeds.
        from products.slack_app.backend.services.slack_auth import write_auth_state_broken

        write_auth_state_broken(self.integration_old.id, error_code="invalid_auth")
        write_auth_state_broken(self.integration_mid.id, error_code="invalid_auth")
        write_auth_state_broken(self.integration_new.id, error_code="invalid_auth")

        result = load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)

        assert result.candidates == []

    def test_transient_auth_test_error_drops_candidate(self):
        # A transient ``auth.test`` failure (Slack 5xx, network blip) leaves
        # the cache untouched but still drops the candidate from THIS
        # invocation's result — we have no proof the token works, so we don't
        # ship the user a probably-broken probe. The next mention retries.
        from products.slack_app.backend.services.slack_auth import get_cached_auth_state

        self.mock_auth_test.side_effect = RuntimeError("boom")

        result = load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)

        assert result.candidates == []
        # Cache untouched: next mention retries instead of inheriting a stale
        # negative verdict.
        assert get_cached_auth_state(self.integration_old.id) is None

    def test_broken_thread_mapping_falls_through_to_healthy_sibling(self):
        # Reproduces the production case: a thread mapping pins routing to an
        # install whose token has since been revoked. With ``drop`` semantics
        # the resolver's "out-of-set" handling in ``resolve_from_candidates``
        # walks past the dead mapping rather than honoring a target the bot
        # can't actually reach.
        #
        # Setup deliberately leaves only ONE healthy sibling (``new``): ``old``
        # is broken and dropped, ``mid`` is also marked broken so the auth
        # filter strips it too. That collapses the candidate list to ``[new]``
        # and the resolver falls through past the dead thread mapping to
        # ``sole_candidate``. Without this constraint the assertion below
        # would have to accept ``needs_picker`` with an empty ``integration``,
        # which can pass vacuously if the resolver silently breaks.
        from products.slack_app.backend.models import SlackThreadTaskMapping
        from products.slack_app.backend.services.slack_auth import write_auth_state_broken, write_auth_state_ok

        write_auth_state_broken(self.integration_old.id, error_code="invalid_auth")
        write_auth_state_broken(self.integration_mid.id, error_code="invalid_auth")
        write_auth_state_ok(self.integration_new.id, bot_user_id="U_NEW_BOT")

        # Thread mapping points at the broken ``old`` install. ``team`` /
        # ``task`` / ``task_run`` aren't relevant to this test's assertions —
        # we only need a mapping row that resolves the mapped integration.
        # ``Task`` / ``TaskRun`` are looked up via the app registry to dodge
        # the circular-import that fires when ``products.tasks`` is imported
        # at module top from this products.slack_app test file.
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(team=self.team_old, title="t")
        task_run = TaskRun.objects.create(team=self.team_old, task=task)
        SlackThreadTaskMapping.objects.create(
            team=self.team_old,
            integration=self.integration_old,
            slack_workspace_id=WORKSPACE,
            channel="C1",
            thread_ts="123.456",
            task=task,
            task_run=task_run,
            mentioning_slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack"],
            slack_user_id=SLACK_USER,
            channel="C1",
            thread_ts="123.456",
        )

        # The healthy sibling is the one the resolver routes to. Strong
        # assertions (instead of ``!= integration_old``) so a regression that
        # returns ``None`` or picks the wrong install fails loudly.
        assert {c.id for c in result.candidates} == {self.integration_new.id}
        assert result.integration == self.integration_new
        assert result.source == "sole_candidate"
