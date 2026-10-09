from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.backend.models import ReviewInstallationClaim, ReviewRepository
from products.review_hog.backend.ownership import RepositoryRef, resolve_owner

INSTALLATION = "1001"
PROJECT_A, PROJECT_B = 11, 22
WEB = RepositoryRef(installation_id=INSTALLATION, github_repo_id=501, full_name="example-org/web")


def row(team_id: int, *, selected: bool, flash_for: str | None = None, **fields: object) -> ReviewRepository:
    values: dict = {"installation_id": INSTALLATION, "github_repo_id": 501, "full_name": "example-org/web", **fields}
    return ReviewRepository(team_id=team_id, selected=selected, flash_for=flash_for, **values)


def all_claim(team_id: int) -> ReviewInstallationClaim:
    return ReviewInstallationClaim(team_id=team_id, installation_id=INSTALLATION, scope="all")


class TestResolveOwner(SimpleTestCase):
    @parameterized.expand(
        [
            ("nobody", [], None, None),
            ("all_claim", [], all_claim(PROJECT_A), PROJECT_A),
            ("selected", [row(PROJECT_B, selected=True)], None, PROJECT_B),
            ("selected_beats_all_claim", [row(PROJECT_B, selected=True)], all_claim(PROJECT_A), PROJECT_B),
            (
                "exception_in_all_project",
                [row(PROJECT_A, selected=False, flash_for="off")],
                all_claim(PROJECT_A),
                PROJECT_A,
            ),
            # An exception without selection does not take the repository from the "all" project.
            (
                "stale_exception_elsewhere",
                [row(PROJECT_B, selected=False, flash_for="off")],
                all_claim(PROJECT_A),
                PROJECT_A,
            ),
            ("stale_exception_alone", [row(PROJECT_B, selected=False, flash_for="off")], None, None),
            # Renames keep the id, so the old name still matches.
            ("renamed", [row(PROJECT_B, selected=True, full_name="example-org/old-web")], None, PROJECT_B),
            # A name match with another id is an older repository that had this name.
            ("reused_name", [row(PROJECT_B, selected=True, github_repo_id=999)], None, None),
            ("id_unknown_yet", [row(PROJECT_B, selected=True, github_repo_id=None)], None, PROJECT_B),
        ]
    )
    def test_resolve_owner(
        self,
        _name: str,
        rows: list[ReviewRepository],
        claim: ReviewInstallationClaim | None,
        expected_team_id: int | None,
    ) -> None:
        owner = resolve_owner(WEB, rows, claim)

        assert (owner.team_id if owner is not None else None) == expected_team_id
