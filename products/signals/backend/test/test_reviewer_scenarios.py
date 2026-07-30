"""Scenario tests for reviewer assignment: seeded history in, suggested reviewers out.

Unlike the single-invariant unit tests, these run the full path a report takes — the cache
is seeded through the real ``rebuild_repository_activity`` join (fake git log + fake GitHub
attribution, GitHub-realistic mixed-case logins), then ``resolve_suggested_reviewers`` runs
against blame commits. Assertions are ordinal (who outranks whom), never score values, so
constant retuning doesn't break them. The persona cast doubles as executable documentation
of the intended assignment behaviour.
"""

from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from posthog.models import Organization, Team
from posthog.models.github_integration_base import GitHubCommitAttribution, GitHubCommitAuthor

from products.signals.backend.report_generation.repo_activity import rebuild_repository_activity
from products.signals.backend.report_generation.resolve_reviewers import (
    MAX_SUGGESTED_REVIEWERS,
    resolve_suggested_reviewers,
)
from products.tasks.backend.facade.repo_activity import RepositoryCommitActivity

REPOSITORY = "acme/app"

# The cast. Logins carry GitHub's canonical casing on purpose — the activity map lowercases
# them at rebuild, and blame lookups must survive that mismatch (a real bug the all-lowercase
# fixtures used to hide).
FOUNDER = ("DepartedFounder", "founder@acme.com")  # heavy blame, no commits in the window
MAINTAINER = ("MariusAndra", "marius@acme.com")  # active in the area, some blame
NEW_JOINER = ("new-joiner", "joiner@acme.com")  # active in the area, no blame
BOT = ("posthog[bot]", "bot@acme.com")  # busiest committer of all, never suggestable
NEIGHBOUR = ("SiblingDev", "sibling@acme.com")  # active in a sibling area only

AREA_PATH = "products/signals/backend/models.py"  # -> area products/signals
SIBLING_PATH = "products/replay/backend/models.py"  # -> area products/replay


def _history() -> tuple[list[RepositoryCommitActivity], dict[str, tuple[str, bool]]]:
    """~40 synthetic commits over the window, newest-first, plus GitHub's sha→login map."""
    commits: list[RepositoryCommitActivity] = []
    attributions: dict[str, tuple[str, bool]] = {}
    plan = [
        # (login, email, is_bot, path, commit_count, newest_days_ago)
        (*MAINTAINER, False, AREA_PATH, 12, 1),
        (*NEW_JOINER, False, AREA_PATH, 8, 2),
        (*BOT, True, AREA_PATH, 15, 0),
        (*NEIGHBOUR, False, SIBLING_PATH, 6, 1),
        # The founder's window activity is zero — their blame commits below predate it.
    ]
    serial = 0
    for login, _email, is_bot, path, count, newest in plan:
        for i in range(count):
            serial += 1
            sha = f"{serial:07d}" + "a" * 33
            commits.append(
                RepositoryCommitActivity(
                    sha=sha,
                    committed_at=(timezone.now() - timedelta(days=newest + i * 2)).isoformat(),
                    paths=[path],
                )
            )
            attributions[sha] = (login, is_bot)
    commits.sort(key=lambda c: c.committed_at, reverse=True)
    return commits, attributions


# Blame commits: SHAs the research findings would carry, resolved via the commit API.
# The founder authored the two most-relevant ones long ago; the maintainer one recent one.
BLAME = {
    "f" * 40: FOUNDER,
    "e" * 40: FOUNDER,
    "d" * 40: MAINTAINER,
    "b" * 40: BOT,
}


class FakeBlameGitHub:
    def get_commit_author_info(self, repository, sha):
        login, _email = BLAME[sha]
        return GitHubCommitAuthor(
            login=login,  # canonical casing, as the API returns it
            name=login,
            commit_url=f"https://github.com/{REPOSITORY}/commit/{sha}",
            file_paths=(AREA_PATH,),
            is_bot=login.endswith("[bot]"),
        )


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-reviewer-scenarios-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-reviewer-scenarios-team")


@pytest.fixture
def seeded_team(team):
    """Seed the activity cache through the real rebuild join, not hand-built rows."""
    commits, attributions = _history()

    class FakeAttributionGitHub:
        def list_commit_attributions(self, repository, *, since, max_pages=150):
            return [
                GitHubCommitAttribution(sha=sha, login=login, is_bot=is_bot)
                for sha, (login, is_bot) in attributions.items()
            ]

    with (
        patch(
            "products.signals.backend.report_generation.repo_activity.collect_repository_commit_activity",
            return_value=commits,
        ),
        patch(
            "products.signals.backend.report_generation.repo_activity.GitHubIntegration.first_for_team_repository",
            return_value=FakeAttributionGitHub(),
        ),
    ):
        rebuild_repository_activity(team.id, REPOSITORY)
    return team


def _resolve(team, blame_shas: list[str]):
    with patch(
        "products.signals.backend.report_generation.resolve_reviewers.GitHubIntegration.first_for_team_repository",
        return_value=FakeBlameGitHub(),
    ):
        return resolve_suggested_reviewers(team.id, REPOSITORY, dict.fromkeys(blame_shas, "relevant"))


@pytest.mark.django_db
class TestReviewerScenarios:
    def test_active_maintainer_outranks_departed_founder(self, seeded_team):
        reviewers = _resolve(seeded_team, ["f" * 40, "e" * 40, "d" * 40])

        logins = [r.login for r in reviewers]
        # The founder owns the two strongest blame commits but left months ago; the
        # maintainer holds weaker blame and current area activity.
        assert logins.index("mariusandra") < logins.index("departedfounder")

    def test_mixed_case_blame_login_is_one_active_candidate(self, seeded_team):
        reviewers = _resolve(seeded_team, ["d" * 40])

        # The API returned MariusAndra, the map stores mariusandra — one entry, top-ranked
        # (active blame author), never a stale-scored duplicate pair.
        assert reviewers[0].login == "mariusandra"
        lowered = [r.login.lower() for r in reviewers]
        assert len(lowered) == len(set(lowered))

    def test_new_joiner_surfaces_when_all_blame_is_stale(self, seeded_team):
        reviewers = _resolve(seeded_team, ["f" * 40, "e" * 40])

        logins = [r.login for r in reviewers]
        # Everyone in blame is gone; the area's actual current contributors fill in.
        assert "mariusandra" in logins
        assert "new-joiner" in logins
        if "departedfounder" in logins:
            assert logins.index("mariusandra") < logins.index("departedfounder")

    def test_bots_never_suggested(self, seeded_team):
        # The bot is both the busiest area committer and a blame author.
        reviewers = _resolve(seeded_team, ["b" * 40, "f" * 40])

        assert all("[bot]" not in r.login for r in reviewers)

    def test_sibling_area_contributor_stays_out_of_a_healthy_area(self, seeded_team):
        reviewers = _resolve(seeded_team, ["d" * 40])

        assert "siblingdev" not in [r.login for r in reviewers]

    def test_at_most_three_and_deterministic(self, seeded_team):
        first = _resolve(seeded_team, ["f" * 40, "e" * 40, "d" * 40])
        second = _resolve(seeded_team, ["f" * 40, "e" * 40, "d" * 40])

        assert len(first) <= MAX_SUGGESTED_REVIEWERS
        assert [(r.login, [c.sha for c in r.commits]) for r in first] == [
            (r.login, [c.sha for c in r.commits]) for r in second
        ]
