import datetime as dt

import pytest
from posthog.test.base import ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from posthog.uuidt import uuid7

from products.replay_vision.backend.queries.session_identity import (
    MAX_IDENTITY_VALUE_LEN,
    fetch_session_person_properties,
    person_display_name,
    person_organization,
)

_START = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_END = _START + dt.timedelta(minutes=5)


class TestFetchSessionPersonProperties(ClickhouseTestMixin):
    @pytest.mark.django_db
    def test_reads_the_recorded_person_identity_properties(self, team) -> None:
        session_id = str(uuid7())
        _create_person(
            team_id=team.pk,
            distinct_ids=["user-1"],
            properties={"email": "rene@customer.example", "name": "Rene Diaz", "org__name": "Customer Co"},
        )
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="user-1",
            timestamp=_START,
            properties={"$session_id": session_id},
        )
        flush_persons_and_events()

        properties = fetch_session_person_properties(
            team=team, session_id=session_id, distinct_id="user-1", start=_START, end=_END
        )

        assert properties["email"] == "rene@customer.example"
        assert properties["name"] == "Rene Diaz"
        assert properties["org__name"] == "Customer Co"

    @pytest.mark.django_db
    def test_ignores_events_another_person_posted_under_the_same_session_id(self, team) -> None:
        # A project's write token is public, so anyone who knows a session id can post an event carrying it
        # under their own distinct id. Attributing the recording to them would persist a spoofed subject on the
        # observation and present it as authoritative, so the query binds to the distinct id the replay names.
        # Only the intruder carries an email, because `any()` skips nulls: were the clause dropped, the
        # aggregate would reach past the subject's missing value and return the intruder's, whatever the row
        # order. Giving both an email would let the assertion pass on luck.
        session_id = str(uuid7())
        _create_person(team_id=team.pk, distinct_ids=["subject"], properties={"name": "Rene Diaz"})
        _create_person(team_id=team.pk, distinct_ids=["intruder"], properties={"email": "attacker@evil.example"})
        for distinct_id in ("subject", "intruder"):
            _create_event(
                team=team,
                event="$pageview",
                distinct_id=distinct_id,
                timestamp=_START,
                properties={"$session_id": session_id},
            )
        flush_persons_and_events()

        properties = fetch_session_person_properties(
            team=team, session_id=session_id, distinct_id="subject", start=_START, end=_END
        )

        assert properties.get("email") is None
        assert properties.get("name") == "Rene Diaz"

    @pytest.mark.django_db
    def test_returns_empty_for_a_session_with_no_events(self, team) -> None:
        assert (
            fetch_session_person_properties(
                team=team, session_id=str(uuid7()), distinct_id="user-1", start=_START, end=_END
            )
            == {}
        )

    @pytest.mark.django_db
    def test_returns_empty_without_a_subject_distinct_id(self, team) -> None:
        # No subject to attribute to, so nothing is read rather than whatever else shares the session id.
        assert (
            fetch_session_person_properties(
                team=team, session_id=str(uuid7()), distinct_id=None, start=_START, end=_END
            )
            == {}
        )


class TestPersonOrganization:
    def test_prefers_the_most_specific_key_the_person_carries(self) -> None:
        # Both keys can sit on one person; a generic `company` is often self-reported free text where the
        # namespaced one comes from the product's own instrumentation.
        assert person_organization({"company": "Typed By Hand", "org__name": "Customer Co"}) == "Customer Co"

    def test_falls_back_through_the_conventional_keys(self) -> None:
        assert person_organization({"company_name": "Customer Co"}) == "Customer Co"

    def test_returns_none_when_no_key_holds_a_usable_value(self) -> None:
        # A blank or non-string value must read as unknown, so the prompt says so instead of naming an empty org.
        assert person_organization({"org__name": "   ", "company": None, "organization": 42}) is None
        assert person_organization({}) is None

    def test_caps_an_oversized_value(self) -> None:
        # Person properties are customer-controlled free text with no length limit, and this renders into a
        # prompt that is cached and re-sent every turn.
        assert person_organization({"org__name": "x" * 5000}) == "x" * MAX_IDENTITY_VALUE_LEN


class TestPersonDisplayName:
    def test_prefers_a_full_name_over_the_split_parts(self) -> None:
        assert person_display_name({"name": "Rene Diaz", "first_name": "Rene"}) == "Rene Diaz"

    def test_joins_first_and_last_name_when_there_is_no_full_name(self) -> None:
        assert person_display_name({"first_name": "Rene", "last_name": "Diaz"}) == "Rene Diaz"

    def test_uses_whichever_name_part_is_present(self) -> None:
        assert person_display_name({"last_name": "Diaz"}) == "Diaz"

    def test_returns_none_when_the_person_carries_no_name(self) -> None:
        assert person_display_name({"email": "rene@customer.example"}) is None

    def test_caps_a_joined_name(self) -> None:
        # Each part is capped, so the join has to be capped too or it lands at twice the limit.
        joined = person_display_name({"first_name": "x" * 5000, "last_name": "y" * 5000})
        assert joined is not None and len(joined) == MAX_IDENTITY_VALUE_LEN
