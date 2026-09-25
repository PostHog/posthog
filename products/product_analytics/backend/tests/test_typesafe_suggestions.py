import json

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import BaseMathType, CountPerActorMathType, FunnelMathType, InsightVizNode, PropertyMathType

from posthog.egress.typesafe.client import ChoiceAnswer, NoulAnswer, SystemOneResult

from products.product_analytics.backend.presentation.typesafe_metadata import (
    DashboardCandidate,
    SubjectContext,
    description_candidates,
    humanize_date_range,
    math_reading,
    suggest_dashboard,
    suggest_tags,
    suggest_title,
    title_candidates,
)

MODULE = "products.product_analytics.backend.presentation.typesafe_metadata"


def _viz(source: dict) -> InsightVizNode:
    return InsightVizNode.model_validate({"kind": "InsightVizNode", "source": source})


def _trends(**kwargs: object) -> InsightVizNode:
    return _viz({"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}], **kwargs})


def _result(answers: dict) -> SystemOneResult:
    return SystemOneResult(model="jev-1.13.0", answers=answers, input_tokens=10)


def _every_series_math() -> list[tuple[str]]:
    values = {
        str(member.value)
        for enum in (BaseMathType, PropertyMathType, CountPerActorMathType, FunnelMathType)
        for member in enum
    }
    values.update({"hogql", "unique_group"})
    return sorted((value,) for value in values if value != "total")


def _series_with(math: str) -> dict:
    node: dict = {"kind": "EventsNode", "event": "$pageview", "math": math}
    if math in {"avg", "sum", "min", "max", "median", "p75", "p90", "p95", "p99"}:
        node["math_property"] = "$session_duration"
    if math == "hogql":
        node["math_hogql"] = "count()"
    if math == "unique_group":
        node["math_group_type_index"] = 0
    return node


class TestTypesafeSuggestionCandidates(SimpleTestCase):
    @parameterized.expand(_every_series_math())
    def test_every_math_reads_in_a_title(self, math: str) -> None:
        # The schema is the source of truth for maths a series can carry. A math with no reading
        # would fall back to a bare event name and describe a different chart.
        query = _viz({"kind": "TrendsQuery", "series": [_series_with(math)]})
        actors = ("group", "groups") if math == "unique_group" else ("user", "users")
        reading = math_reading(query.source.series[0], "pageviews", actors)
        assert reading.title_base, math
        assert "pageviews" in reading.title_base
        assert reading.summary and "{" not in reading.summary
        assert reading.title_base in title_candidates(SubjectContext(subject="insight", query=query))

    def test_group_aggregation_names_the_group_type(self) -> None:
        names = {0: ("organization", "organizations")}
        by_series = SubjectContext(
            subject="insight",
            query=_viz({"kind": "TrendsQuery", "series": [_series_with("unique_group")]}),
            group_type_names=names,
        )
        by_query = SubjectContext(
            subject="insight",
            query=_viz({"kind": "TrendsQuery", "series": [_series_with("dau")], "aggregation_group_type_index": 0}),
            group_type_names=names,
        )
        assert title_candidates(by_series)[0] == "Unique organizations with pageviews"
        assert title_candidates(by_query)[0] == "Unique organizations with pageviews"

    def test_trends_title_candidates_humanize_the_series_and_include_the_current_name(self) -> None:
        context = SubjectContext(
            subject="insight",
            name="My weird name",
            query=_trends(
                interval="day",
                breakdownFilter={"breakdown": "$browser"},
                dateRange={"date_from": "-7d"},
            ),
        )
        candidates = title_candidates(context)

        assert candidates[0] == "My weird name"
        assert "Pageviews by browser" in candidates
        assert "Daily pageviews" in candidates
        assert "Pageviews over the last 7 days" in candidates
        assert len(candidates) == len({c.lower() for c in candidates})

    def test_single_series_math_lands_in_the_title_base(self) -> None:
        context = SubjectContext(
            subject="insight",
            query=_viz(
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$autocapture", "math": "first_time_for_user"}],
                    "breakdownFilter": {"breakdown": "$current_url"},
                }
            ),
        )
        titles = title_candidates(context)

        assert titles[0] == "First-ever autocaptured interactions per user"
        assert "First-ever autocaptured interactions per user by current URL" in titles
        assert "Autocaptured interactions by current URL" in titles
        assert any(
            candidate.startswith("Shows first-ever autocaptured interactions per user")
            and candidate.endswith("broken down by current URL.")
            for candidate in description_candidates(context)
        )

    def test_formula_trends_lead_with_the_ratio_and_keep_series_distinct(self) -> None:
        context = SubjectContext(
            subject="insight",
            query=_viz(
                {
                    "kind": "TrendsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": "$pageview", "math": "total"},
                        {"kind": "EventsNode", "event": "$pageview", "math": "dau"},
                    ],
                    "trendsFilter": {"formulaNodes": [{"formula": "A/B"}]},
                }
            ),
        )
        titles = title_candidates(context)

        assert titles[0] == "Total pageviews per user"
        assert "Pageviews and pageviews" not in titles
        assert "Total pageviews and unique users for pageviews" in titles
        assert not any(candidate.startswith("Unique users for total pageviews") for candidate in titles)
        assert any(
            candidate.startswith("Divides total pageviews by the number of unique users")
            for candidate in description_candidates(context)
        )

    def test_funnel_description_candidates_name_the_first_and_last_step(self) -> None:
        context = SubjectContext(
            subject="insight",
            query=_viz(
                {
                    "kind": "FunnelsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": "user_signed_up"},
                        {"kind": "EventsNode", "event": "purchase"},
                    ],
                }
            ),
        )
        assert "Shows where users drop off between user signed up and purchase." in description_candidates(context)

    def test_dashboard_candidates_come_from_themes_and_tile_names(self) -> None:
        context = SubjectContext(subject="dashboard", tile_names=("Signups", "Activation rate"))
        titles = title_candidates(context)
        assert "Acquisition overview" in titles
        assert "Signups and Activation rate" in titles
        assert "Brings together 2 insights, including Signups and Activation rate." in description_candidates(context)

    @parameterized.expand(
        [
            ("-7d", "the last 7 days"),
            ("-1m", "the last month"),
            ("mStart", "this month"),
            ("all", "all time"),
            ("2024-01-15T00:00:00Z", "since 2024-01-15"),
            (None, None),
        ]
    )
    def test_humanize_date_range(self, date_from: str | None, expected: str | None) -> None:
        assert humanize_date_range(date_from) == expected


class TestTypesafeSuggestionRanking(SimpleTestCase):
    def test_title_returns_the_candidate_jev_picked(self) -> None:
        context = SubjectContext(subject="insight", query=_trends())
        candidates = title_candidates(context)
        picked_key = f"c{candidates.index('Pageviews over time')}"
        with patch(f"{MODULE}.system_one") as system_one:
            system_one.return_value = _result(
                {"title": ChoiceAnswer(choice=picked_key, confidence=0.7, probabilities={})}
            )
            suggestion = suggest_title(context)

        assert suggestion.value == "Pageviews over time"
        assert suggestion.confidence == 0.7
        # The current name is user text: it must travel in state, never in the instructions.
        sent = system_one.call_args.kwargs
        assert sent["state"]["subject"]["name"] == ""
        assert sent["state"]["subject"]["summary"][0] == "Type: Trends"
        assert "query" not in sent["state"]["subject"]
        assert "Pageviews" not in sent["questions"]["title"].instructions

    def test_state_carries_filter_keys_but_never_filter_values(self) -> None:
        context = SubjectContext(
            subject="insight",
            query=_trends(
                properties=[
                    {
                        "type": "event",
                        "key": "$current_url",
                        "operator": "icontains",
                        "value": "secret-customer@example.com",
                    }
                ],
                trendsFilter={"display": "ActionsBar"},
            ),
        )
        with patch(f"{MODULE}.system_one") as system_one:
            system_one.return_value = _result({"title": ChoiceAnswer(choice="c0", confidence=0.7, probabilities={})})
            suggest_title(context)

        state = json.dumps(system_one.call_args.kwargs["state"])
        assert "secret-customer" not in state
        assert "Filtered to: current URL contains a specific value" in state
        assert "Chart: bar" in state

    @parameterized.expand(
        [
            ("plain_value", "$current_url", "icontains", "tomato", "current URL contains tomato"),
            ("email_key", "email", "exact", "someone@example.com", "email is a specific value"),
            ("email_value", "note", "exact", "someone@example.com", "note is a specific value"),
            ("long_token", "token", "exact", "a" * 61, "token is a specific value"),
            ("is_set", "$browser", "is_set", None, "browser is set"),
        ]
    )
    def test_filter_phrases_quote_plain_values_and_redact_personal_ones(
        self, _name: str, key: str, operator: str, value: object, expected: str
    ) -> None:
        context = SubjectContext(
            subject="insight",
            query=_trends(
                series=[
                    {
                        "kind": "EventsNode",
                        "event": "$autocapture",
                        "math": "dau",
                        "properties": [{"type": "event", "key": key, "operator": operator, "value": value}],
                    }
                ]
            ),
        )
        titles = title_candidates(context)
        assert titles[0] == f"Unique users with autocaptured interactions where {expected}"
        if value and "example.com" not in str(value) and len(str(value)) < 61:
            assert any(str(value) in title for title in titles)
        else:
            assert not any(str(value) in title for title in titles if value)

    def test_runner_up_is_the_second_most_likely_candidate(self) -> None:
        context = SubjectContext(subject="insight", query=_trends())
        with patch(f"{MODULE}.system_one") as system_one:
            system_one.return_value = _result(
                {"title": ChoiceAnswer(choice="c0", confidence=0.5, probabilities={"c0": 0.5, "c1": 0.1, "c2": 0.4})}
            )
            suggestion = suggest_title(context)
        assert suggestion.runner_up == suggestion.candidates[2]

    def test_tags_keep_only_confident_matches_and_never_invent_one(self) -> None:
        context = SubjectContext(subject="insight", name="Signups by country", query=_trends())
        with patch(f"{MODULE}.system_one") as system_one:
            system_one.return_value = _result(
                {
                    "t0": NoulAnswer(probability=0.9),
                    "t1": NoulAnswer(probability=0.2),
                    "t2": NoulAnswer(probability=0.6),
                }
            )
            suggestion = suggest_tags(context, ["growth", "billing", "marketing"])

        assert suggestion.tags == ("growth", "marketing")
        assert system_one.call_args.kwargs["state"]["tags"] == {"t0": "growth", "t1": "billing", "t2": "marketing"}

    def test_tags_without_any_existing_tag_skip_the_call(self) -> None:
        with patch(f"{MODULE}.system_one") as system_one:
            assert suggest_tags(SubjectContext(subject="insight"), []).tags == ()
        system_one.assert_not_called()

    @parameterized.expand([("d1", 42), ("none", None)])
    def test_dashboard_maps_the_pick_back_to_an_id(self, choice: str, expected: int | None) -> None:
        dashboards = [DashboardCandidate(id=7, name="Revenue"), DashboardCandidate(id=42, name="Growth")]
        with patch(f"{MODULE}.system_one") as system_one:
            system_one.return_value = _result(
                {"dashboard": ChoiceAnswer(choice=choice, confidence=0.55, probabilities={})}
            )
            suggestion = suggest_dashboard(SubjectContext(subject="insight", name="Signups"), dashboards)

        assert suggestion.dashboard_id == expected
        assert "none" in system_one.call_args.kwargs["questions"]["dashboard"].criteria
