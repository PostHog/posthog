from datetime import UTC, datetime
from uuid import uuid4

from django.test import SimpleTestCase

from posthog.schema import (
    ElementPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelsFilter,
    FunnelsQuery,
    Key10,
    PropertyOperator,
    StepOrderValue,
)

from products.user_journeys.backend.facade import api
from products.user_journeys.backend.facade.contracts import ElementClickStep, Journey, PageviewStep
from products.user_journeys.backend.facade.enums import JourneySource, UrlMatching


class TestJourneyToFunnelsQuery(SimpleTestCase):
    def test_mixed_pageview_and_click_journey(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        journey = Journey(
            id=uuid4(),
            team_id=1,
            name="Sign up",
            description="",
            steps=[
                PageviewStep(url="/pricing", url_matching=UrlMatching.CONTAINS),
                ElementClickStep(
                    selector="button.signup",
                    text="Sign up",
                    href="/signup",
                    url="^https://example\\.com/pricing",
                    url_matching=UrlMatching.REGEX,
                ),
                ElementClickStep(selector="#submit"),
                PageviewStep(url="https://example.com/welcome"),
            ],
            conversion_window_minutes=45,
            source=JourneySource.TOOLBAR,
            created_by_id=None,
            created_at=now,
            updated_at=now,
        )

        assert api.journey_to_funnels_query(journey) == FunnelsQuery(
            series=[
                EventsNode(
                    custom_name="Pageview of /pricing",
                    event="$pageview",
                    properties=[
                        EventPropertyFilter(key="$current_url", operator=PropertyOperator.ICONTAINS, value="/pricing")
                    ],
                ),
                EventsNode(
                    custom_name='Click on "Sign up"',
                    event="$autocapture",
                    properties=[
                        ElementPropertyFilter(
                            key=Key10.SELECTOR, operator=PropertyOperator.EXACT, value="button.signup"
                        ),
                        ElementPropertyFilter(key=Key10.TEXT, operator=PropertyOperator.EXACT, value="Sign up"),
                        ElementPropertyFilter(key=Key10.HREF, operator=PropertyOperator.EXACT, value="/signup"),
                        EventPropertyFilter(
                            key="$current_url",
                            operator=PropertyOperator.REGEX,
                            value="^https://example\\.com/pricing",
                        ),
                    ],
                ),
                EventsNode(
                    custom_name="Click on #submit",
                    event="$autocapture",
                    properties=[
                        ElementPropertyFilter(key=Key10.SELECTOR, operator=PropertyOperator.EXACT, value="#submit")
                    ],
                ),
                EventsNode(
                    custom_name="Pageview of https://example.com/welcome",
                    event="$pageview",
                    properties=[
                        EventPropertyFilter(
                            key="$current_url", operator=PropertyOperator.EXACT, value="https://example.com/welcome"
                        )
                    ],
                ),
            ],
            funnelsFilter=FunnelsFilter(
                funnelAggregateByHogQL="properties.$session_id",
                funnelOrderType=StepOrderValue.ORDERED,
                funnelWindowInterval=45,
                funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.MINUTE,
            ),
        )
