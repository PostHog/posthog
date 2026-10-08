"""Tests for the visual_review_debt_digest management command."""

import pytest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models.team.team import Team

from products.visual_review.backend.logic import repos
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_REPO = "org/shared-by-two"


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestDebtDigestCommand:
    @pytest.fixture
    def two_teams(self, team):
        other_team = Team.objects.create(organization=team.organization, name="other")
        mine = repos.create_repo(team_id=team.id, repo_external_id=66661, repo_full_name=_REPO)
        theirs = repos.create_repo(team_id=other_team.id, repo_external_id=66662, repo_full_name=_REPO)
        return mine, theirs

    def test_a_name_two_teams_registered_asks_which_one(self, two_teams) -> None:
        with pytest.raises(CommandError, match="more than one team"):
            call_command("visual_review_debt_digest", "--repo", _REPO)

    @pytest.mark.parametrize("which", [0, 1])
    def test_team_id_picks_the_row_that_team_owns(self, two_teams, which: int) -> None:
        wanted = two_teams[which]

        with patch("products.visual_review.backend.logic.debt_digest.send_debt_digest", return_value=[]) as send:
            call_command("visual_review_debt_digest", "--repo", _REPO, "--team-id", str(wanted.team_id))

        assert send.call_args.args[0].id == wanted.id

    def test_an_unknown_repo_is_named_in_the_error(self) -> None:
        with pytest.raises(CommandError, match="No visual review repo named org/nope"):
            call_command("visual_review_debt_digest", "--repo", "org/nope")
