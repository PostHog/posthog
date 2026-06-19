import pytest

from django.apps import apps

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.slack_app.backend.services.integration_resolver import load_integrations

WORKSPACE = "T_WS"
SLACK_USER = "U001"


class TestResolveIntegration:
    @pytest.fixture(autouse=True)
    def setup(self, db):
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


class TestLoadIntegrationsAuthStateFilter:
    """Covers the cached-auth-state pre-filter in ``load_integrations``.

    The scenario mirrors Zendesk #60619: an org has three Slack rows for the
    same workspace, one of them has a revoked bot token, the resolver used to
    pick that one as ``candidates[0]`` and silently broke every mention. With
    the cache populated, the broken install is demoted so a healthy probe is
    picked first.
    """

    @pytest.fixture(autouse=True)
    def setup(self, db):
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

    def test_cold_cache_preserves_pk_ascending(self):
        # Empty cache → fall back to today's behavior so we don't regress
        # mentions during the first deploy hours or after a Redis flush.
        result = load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)
        assert self._candidate_ids(result.candidates) == [
            self.integration_old.id,
            self.integration_mid.id,
            self.integration_new.id,
        ]

    def test_broken_candidate_demoted_to_end(self):
        # Old install's token is dead — should land last, but stay in the
        # list so a stale negative verdict can't strand the workspace.
        from products.slack_app.backend.services.slack_auth import write_auth_state_broken

        write_auth_state_broken(self.integration_old.id, error_code="invalid_auth")

        result = load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)

        assert self._candidate_ids(result.candidates) == [
            self.integration_mid.id,
            self.integration_new.id,
            self.integration_old.id,
        ]

    def test_healthy_freshest_wins_over_unknown(self):
        # ``new`` was confirmed healthy most recently — surface it ahead of
        # the older PKs whose verdict we haven't seen yet. Matches the
        # "Hubert just reconnected Production" scenario.
        from products.slack_app.backend.services.slack_auth import write_auth_state_ok

        write_auth_state_ok(self.integration_new.id, bot_user_id="U_NEW")

        result = load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)

        assert result.candidates[0].id == self.integration_new.id
        # ``old`` / ``mid`` are unknown; keep PK ascending behind the healthy
        # one so today's tie-breaker stays predictable.
        assert self._candidate_ids(result.candidates)[1:] == [
            self.integration_old.id,
            self.integration_mid.id,
        ]

    def test_all_broken_returns_full_list_so_workspace_self_heals(self):
        # If every cache entry is ``ok=false`` (e.g. a transient outage was
        # misclassified as auth-class earlier) we must NOT strand the
        # workspace. Return them all; a real call that now succeeds will
        # flip the cache back to healthy via the success-path write hook.
        from products.slack_app.backend.services.slack_auth import write_auth_state_broken

        write_auth_state_broken(self.integration_old.id, error_code="invalid_auth")
        write_auth_state_broken(self.integration_mid.id, error_code="invalid_auth")
        write_auth_state_broken(self.integration_new.id, error_code="invalid_auth")

        result = load_integrations(slack_team_id=WORKSPACE, kinds=["slack"], slack_user_id=SLACK_USER)

        assert {c.id for c in result.candidates} == {
            self.integration_old.id,
            self.integration_mid.id,
            self.integration_new.id,
        }
