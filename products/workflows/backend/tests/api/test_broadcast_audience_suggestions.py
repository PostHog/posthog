from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models import PropertyDefinition
from posthog.test.persons import create_person

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.facade.contracts import AudienceKind
from products.workflows.backend.services.audience_suggestions.audience import cohort_filters, reachable_count
from products.workflows.backend.services.audience_suggestions.planner import AudienceIdea
from products.workflows.backend.services.audience_suggestions.service import _cache_key

SERVICE = "products.workflows.backend.services.audience_suggestions.service"
FLAG = f"{SERVICE}.posthoganalytics.feature_enabled"


def _idea(
    kind: AudienceKind,
    event: str,
    missing_event: str | None = None,
    window_days: int = 14,
    min_count: int | None = None,
) -> AudienceIdea:
    return AudienceIdea(
        name=f"People who did {event}",
        description="People to tell about the next step.",
        reason="They are worth a note.",
        kind=kind,
        event=event,
        missing_event=missing_event,
        window_days=window_days,
        min_count=min_count,
    )


class TestBroadcastAudienceSuggestions(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.delete(_cache_key(self.team.id))
        self.flag = patch(FLAG, return_value=True).start()
        # FLAG patches the shared feature_enabled, which the privacy mode check reads too.
        patch(f"{SERVICE}.is_privacy_mode_enabled", return_value=False).start()
        self.addCleanup(patch.stopall)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        now = datetime.now(UTC)
        window_start = (now - timedelta(days=14)).replace(hour=0, minute=0, second=0, microsecond=0)
        # 12 recent sign-ups without a project, one with a project, and two without a usable email address.
        for index in range(12):
            self._person(f"new-{index}", [("signed_up", now - timedelta(days=2))])
        self._person(
            "activated", [("signed_up", now - timedelta(days=2)), ("project_created", now - timedelta(days=1))]
        )
        self._person("no-email", [("signed_up", now - timedelta(days=2))], email=None)
        self._person("empty-email", [("signed_up", now - timedelta(days=2))], email="")
        # The window starts at the start of the day, like the cohort's relative dates.
        self._person("first-day", [("signed_up", window_start + timedelta(hours=1))])
        self._person("day-before", [("signed_up", window_start - timedelta(hours=1))])
        # 11 regulars with 3 pageviews this week, and 11 people last seen 40 days ago.
        for index in range(11):
            self._person(f"regular-{index}", [("$pageview", now - timedelta(days=day)) for day in (1, 2, 3)])
            self._person(f"lapsed-{index}", [("$pageview", now - timedelta(days=40))])
        flush_persons_and_events()

    def _person(self, distinct_id: str, events: list[tuple[str, datetime]], email: str | None = "set") -> None:
        properties = {} if email is None else {"email": f"{distinct_id}@example.com" if email == "set" else email}
        create_person(team=self.team, distinct_ids=[distinct_id], properties=properties)
        for event, timestamp in events:
            _create_event(team=self.team, event=event, distinct_id=distinct_id, timestamp=timestamp)

    def _list(self) -> dict:
        url = f"/api/projects/{self.team.id}/broadcast_audience_suggestions/"
        # Celery runs eagerly in tests, so the run that generate starts has finished when it returns.
        started = self.client.post(f"{url}generate/", {}, format="json")
        assert started.status_code == 200, started.json()
        response = self.client.get(f"{url}current/")
        assert response.status_code == 200, response.json()
        return response.json()

    @parameterized.expand(
        [
            ("not_yet", "signed_up", "project_created", 14, None, 13),
            ("regulars", "$pageview", None, 7, 3, 11),
            ("lapsed", "$pageview", None, 30, None, 11),
        ]
    )
    def test_card_count_matches_the_calculated_cohort(
        self,
        kind: AudienceKind,
        event: str,
        missing_event: str | None,
        window_days: int,
        min_count: int | None,
        expected: int,
    ) -> None:
        filters = cohort_filters(
            kind=kind, event=event, missing_event=missing_event, window_days=window_days, min_count=min_count
        )
        cohort = Cohort.objects.create(team=self.team, name="Audience", filters=filters)
        cohort.calculate_people_ch(pending_version=0)
        cohort.refresh_from_db()

        count = reachable_count(
            self.team, kind=kind, event=event, missing_event=missing_event, window_days=window_days, min_count=min_count
        )
        assert count == expected
        assert cohort.count == expected

    @patch(f"{SERVICE}.suggest_audiences")
    def test_keeps_valid_audiences_one_per_kind_and_caches_them(self, suggest: MagicMock) -> None:
        suggest.return_value = [
            _idea("not_yet", "signed_up", "project_created"),
            _idea("not_yet", "made_up_event", "project_created"),
            _idea("not_yet", "signed_up", "signed_up"),
            # Fewer than 10 people with an email address.
            _idea("regulars", "project_created", window_days=7, min_count=3),
            _idea("lapsed", "$pageview", window_days=30),
            _idea("not_yet", "$pageview", "project_created"),
        ]

        body = self._list()

        assert body["status"] == "ready"
        assert [(s["kind"], s["event"], s["reachable_count"]) for s in body["suggestions"]] == [
            ("not_yet", "signed_up", 13),
            ("lapsed", "$pageview", 11),
            ("not_yet", "$pageview", 11),
        ]
        prompt_events = dict(suggest.call_args.kwargs["events"])
        assert prompt_events["$pageview"] == 33
        assert self._list()["suggestions"] == body["suggestions"]
        assert suggest.call_count == 1

    @patch(f"{SERVICE}.reachable_count")
    @patch(f"{SERVICE}.suggest_audiences")
    def test_an_audience_too_costly_to_count_drops_only_that_card(self, suggest: MagicMock, count: MagicMock) -> None:
        suggest.return_value = [
            _idea("lapsed", "$pageview", window_days=30),
            _idea("not_yet", "signed_up", "project_created"),
        ]

        def size(team: object, *, kind: AudienceKind, **_: object) -> int:
            if kind == "lapsed":
                raise ClickHouseQueryTimeOut()
            return 13

        count.side_effect = size

        body = self._list()

        assert body["status"] == "ready"
        assert [(s["kind"], s["reachable_count"]) for s in body["suggestions"]] == [("not_yet", 13)]

    @parameterized.expand(
        [
            ("ai_not_approved", False, True, False, 200, "ai_not_approved"),
            ("flag_off", True, False, False, 403, None),
            ("email_hidden_from_the_user", True, True, True, 403, None),
        ]
    )
    @patch(f"{SERVICE}.suggest_audiences")
    def test_runs_nothing_without_consent_or_flag(
        self,
        _name: str,
        approved: bool,
        flag_on: bool,
        email_restricted: bool,
        status_code: int,
        status: str | None,
        suggest: MagicMock,
    ) -> None:
        self.flag.return_value = flag_on
        self.organization.is_ai_data_processing_approved = approved
        if email_restricted:
            self.organization.available_product_features = [
                {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
            ]
            email = PropertyDefinition.objects.create(
                team=self.team, name="email", property_type="String", type=PropertyDefinition.Type.PERSON
            )
            PropertyAccessControl.objects.create(
                team=self.team, property_definition=email, access_level=PropertyAccessLevel.NONE.value
            )
        self.organization.save()

        response = self.client.post(f"/api/projects/{self.team.id}/broadcast_audience_suggestions/generate/", {})

        assert response.status_code == status_code
        if status:
            assert response.json()["status"] == status
        suggest.assert_not_called()
