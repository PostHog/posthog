import pytest

from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.services.workspace_integrations import (
    get_team_workspace_integration,
    get_workspace_integration,
    require_workspace_integration,
    workspace_integration_exists,
    workspace_integrations,
)

WORKSPACE = "T_WS"
OTHER_WORKSPACE = "T_OTHER"


def _mk(team: Team, workspace: str = WORKSPACE, **extra) -> Integration:
    return Integration.objects.create(
        team=team, kind="slack", integration_id=workspace, sensitive_config={"access_token": "xoxb"}, **extra
    )


class TestWorkspaceIntegrations:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        organization = Organization.objects.create(name="Org")
        self.team_a = Team.objects.create(organization=organization, name="A")
        self.team_b = Team.objects.create(organization=organization, name="B")
        self.row_a = _mk(self.team_a)
        self.row_b = _mk(self.team_b)
        self.row_other_workspace = _mk(self.team_a, OTHER_WORKSPACE)

    def test_two_teams_in_one_workspace_resolve_their_own_rows(self):
        assert get_workspace_integration(self.row_a.id, WORKSPACE) == self.row_a
        assert get_workspace_integration(self.row_b.id, WORKSPACE) == self.row_b
        assert get_team_workspace_integration(self.team_a.id, WORKSPACE) == self.row_a
        assert get_team_workspace_integration(self.team_b.id, WORKSPACE) == self.row_b
        assert [row.id for row in workspace_integrations(WORKSPACE)] == sorted([self.row_a.id, self.row_b.id])

    def test_id_from_another_workspace_returns_none(self):
        assert get_workspace_integration(self.row_other_workspace.id, WORKSPACE) is None
        assert not workspace_integration_exists(self.row_other_workspace.id, WORKSPACE)
        assert get_team_workspace_integration(self.team_b.id, OTHER_WORKSPACE) is None

    @pytest.mark.parametrize(
        "make_row",
        [
            pytest.param(
                lambda team: IntegrationManager.slack.token.create(
                    team.id, external_id=WORKSPACE, config={}, sensitive_config={"access_token": "xoxb"}
                ),
                id="token_auth",
            ),
            pytest.param(
                lambda team: _mk(team, config={"warehouse_source_type": "Stripe"}),
                id="warehouse_source_marked",
            ),
        ],
    )
    def test_rows_outside_the_oauth_scope_are_excluded(self, make_row):
        organization = Organization.objects.create(name="Org2")
        team = Team.objects.create(organization=organization, name="C")
        row = make_row(team)

        assert get_workspace_integration(row.id, WORKSPACE) is None
        assert not workspace_integration_exists(row.id, WORKSPACE)
        assert get_team_workspace_integration(team.id, WORKSPACE) is None
        assert row.id not in [r.id for r in workspace_integrations(WORKSPACE)]

    @pytest.mark.parametrize(
        "make_id,found",
        [
            pytest.param(lambda row: row.id, True, id="int"),
            pytest.param(lambda row: str(row.id), True, id="numeric_string"),
            pytest.param(lambda row: True, False, id="bool"),
            pytest.param(lambda row: "abc", False, id="non_numeric_string"),
            pytest.param(lambda row: "", False, id="empty_string"),
            pytest.param(lambda row: None, False, id="none"),
            pytest.param(lambda row: 1.5, False, id="float"),
            pytest.param(lambda row: 10**30, False, id="out_of_range_int"),
        ],
    )
    def test_id_types(self, make_id, found):
        wanted = make_id(self.row_a)

        assert (get_workspace_integration(wanted, WORKSPACE) is not None) is found
        assert workspace_integration_exists(wanted, WORKSPACE) is found

    def test_require_raises_when_missing(self):
        assert require_workspace_integration(self.row_a.id, WORKSPACE) == self.row_a
        with pytest.raises(IntegrationNotFound):
            require_workspace_integration(self.row_other_workspace.id, WORKSPACE)

    def test_rows_come_with_team_and_organization_loaded(self, django_assert_num_queries):
        rows = workspace_integrations(WORKSPACE)
        with django_assert_num_queries(0):
            assert {row.team.organization.name for row in rows} == {"Org"}
        single = get_workspace_integration(self.row_a.id, WORKSPACE)
        assert single is not None
        with django_assert_num_queries(0):
            assert single.team.organization.name == "Org"
