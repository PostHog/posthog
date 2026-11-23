from datetime import date

import pytest

from posthog.models import Team, User

from products.today.backend.facade.testing import highlight_context
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.wizard.backend.facade.today_highlights import HIGHLIGHT_SOURCES

from .test_logic import _scan


def _found(team: Team, user: User) -> list[tuple[str, str, str | None]]:
    source = next(s for s in HIGHLIGHT_SOURCES if s.name == "wizard_unconnected_sources")
    found = source.find(highlight_context(team=team, user=user, today=date(2026, 11, 13)))
    return [(item.title, item.detail, item.url) for item in found.items]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "detected, connected, deleted, expected",
    [
        pytest.param([], [], [], [], id="nothing detected"),
        pytest.param(["Stripe"], ["Stripe"], [], [], id="every detected source is connected"),
        pytest.param(
            ["Stripe", "Postgres"],
            ["Postgres"],
            [],
            [
                (
                    "Connect Stripe, found in your codebase",
                    "Sync its data into PostHog to query it next to your product data.",
                    "/data-warehouse/new-source?kind=Stripe",
                )
            ],
            id="one left links to its own setup form",
        ),
        pytest.param(
            ["Stripe"],
            [],
            ["Stripe"],
            [
                (
                    "Connect Stripe, found in your codebase",
                    "Sync its data into PostHog to query it next to your product data.",
                    "/data-warehouse/new-source?kind=Stripe",
                )
            ],
            id="a deleted source does not count as connected",
        ),
    ],
)
def test_offers_one_row_for_detected_sources_the_project_has_not_connected(
    team: Team, user: User, detected: list[str], connected: list[str], deleted: list[str], expected: list
) -> None:
    _scan(team, "s1", 0, detected)
    for source_type in connected:
        ExternalDataSource.objects.create(team=team, source_type=source_type, job_inputs={})
    for source_type in deleted:
        ExternalDataSource.objects.create(team=team, source_type=source_type, job_inputs={}, deleted=True)

    assert _found(team, user) == expected


@pytest.mark.django_db
def test_several_sources_share_one_row_that_opens_the_source_catalog(team: Team, user: User) -> None:
    _scan(team, "s1", 0, ["Stripe", "Postgres", "Hubspot", "Zendesk"])

    [(title, detail, url)] = _found(team, user)

    assert title == "Connect 4 data sources found in your codebase"
    assert detail.endswith(" and 1 more. Sync their data into PostHog to query it next to your product data.")
    assert url == "/data-warehouse/new-source"
