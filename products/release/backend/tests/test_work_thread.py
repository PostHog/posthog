from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from unittest import TestCase

from parameterized import parameterized

from products.release.backend.facade.contracts import (
    LinkedBroadcastDTO,
    LinkedSurveyDTO,
    ReleaseDTO,
    ReleaseFlagDetails,
    WorkEarlyAccessFeature,
    WorkExperiment,
    WorkFlag,
    WorkFlagCondition,
)
from products.release.backend.logic.work_thread import ReleaseWorkFacts, is_in_flight, release_work_thread
from products.today.backend.facade.contracts import WorkStep, WorkThread
from products.today.backend.facade.enums import WorkHelperMode, WorkOptionKind, WorkRunType
from products.today.backend.facade.testing import assert_work_threads_well_formed

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
RELEASE_ID = UUID("0193a000-0000-7000-8000-000000000001")
SURVEY_ID = UUID("0193a000-0000-7000-8000-000000000002")
BROADCAST_ID = UUID("0193a000-0000-7000-8000-000000000003")
EARLY_ACCESS_ID = UUID("0193a000-0000-7000-8000-000000000004")


def flag(
    flag_id: int = 1,
    key: str = "quiet-theme",
    rollout: float | None = 100,
    property_count: int = 0,
    **changes: Any,
) -> WorkFlag:
    fields: dict[str, Any] = {
        "id": flag_id,
        "key": key,
        "active": True,
        "archived": False,
        "created_at": NOW - timedelta(days=50),
        "is_v1_config": True,
        "aggregation_group_type_index": None,
        "conditions": (
            WorkFlagCondition(
                property_count=property_count,
                rollout_percentage=rollout,
                variant=None,
                aggregation_group_type_index=None,
            ),
        ),
        "variants": (),
        "early_exit": False,
        "feature_enrollment": False,
        "holdout_exclusion_percentage": 0,
    }
    return WorkFlag(**{**fields, **changes})


def experiment(status: str, experiment_id: int = 7, flag_key: str = "quiet-theme", **changes: Any) -> WorkExperiment:
    fields: dict[str, Any] = {
        "id": experiment_id,
        "name": "Quiet theme test",
        "feature_flag_key": flag_key,
        "status": status,
        "start_date": None if status == "draft" else NOW - timedelta(days=3),
        "end_date": NOW - timedelta(days=1) if status == "stopped" else None,
        "archived": False,
        "conclusion": None,
        "conclusion_comment": None,
    }
    return WorkExperiment(**{**fields, **changes})


def early_access(stage: str, flag_id: int = 1) -> WorkEarlyAccessFeature:
    return WorkEarlyAccessFeature(
        id=EARLY_ACCESS_ID,
        name="Quiet theme beta",
        stage=stage,
        created_at=NOW - timedelta(days=10),
        feature_flag_id=flag_id,
    )


def thread(
    flags: tuple[WorkFlag, ...] = (flag(),),
    *,
    linked_flag_ids: list[int] | None = None,
    has_hidden_flags: bool = False,
    experiments: tuple[WorkExperiment, ...] = (),
    early_access_features: tuple[WorkEarlyAccessFeature, ...] = (),
    incomplete_flag_ids: frozenset[int] = frozenset(),
    surveys: tuple[LinkedSurveyDTO, ...] = (),
    broadcasts: tuple[LinkedBroadcastDTO, ...] = (),
    metric_insight_ids: list[int] | None = None,
    can_edit: bool = True,
) -> WorkThread:
    release = ReleaseDTO(
        id=RELEASE_ID,
        name="Quiet theme",
        description="",
        owner=None,
        feature_flag_ids=[item.id for item in flags] if linked_flag_ids is None else linked_flag_ids,
        has_hidden_flags=has_hidden_flags,
        broadcast_ids=[broadcast.id for broadcast in broadcasts],
        broadcasts=list(broadcasts),
        survey_ids=[survey.id for survey in surveys],
        surveys=list(surveys),
        insight_ids=[],
        insights=[],
        metric_insight_ids=[] if metric_insight_ids is None else metric_insight_ids,
        metric_goals=[],
        created_at=NOW - timedelta(days=40),
    )
    work = ReleaseWorkFacts(
        release=release,
        details=ReleaseFlagDetails(
            flags=flags,
            experiments=experiments,
            early_access_features=early_access_features,
            incomplete_flag_ids=incomplete_flag_ids,
        ),
        now=NOW,
        can_edit=can_edit,
    )
    result = release_work_thread(work)
    assert_work_threads_well_formed([result])
    return result


def current(result: WorkThread) -> WorkStep:
    return result.line.steps[-1]


def next_labels(result: WorkThread) -> list[str]:
    return [option.label for option in current(result).options if option.kind == WorkOptionKind.NEXT]


def alongside_keys(result: WorkThread) -> list[str]:
    return [option.key for option in current(result).options if option.kind == WorkOptionKind.ALONGSIDE]


SURVEY = LinkedSurveyDTO(
    id=SURVEY_ID,
    name="Quiet theme feedback",
    created_at=NOW - timedelta(days=5),
    start_date=NOW - timedelta(days=4),
    end_date=None,
    linked_flag_id=1,
    archived=False,
)
BROADCAST = LinkedBroadcastDTO(id=BROADCAST_ID, name="Launch email", status="active", recent_sends=[])
PARTIAL = flag(rollout=50)
ARCHIVED = flag(active=False, archived=True)


class TestReleaseWorkThread(TestCase):
    @parameterized.expand(
        [
            ("every_linked_flag_visible", (flag(),), [1], False, "Rolled out", ["Clean up the flag"]),
            ("a_linked_flag_hidden", (flag(),), [1], True, "Behind a flag", []),
            ("every_linked_flag_hidden", (), [], True, "Behind a flag", []),
            ("no_flag_linked", (), [], False, "Planned", ["Link a feature flag", "Create a flag"]),
        ]
    )
    def test_stage_and_next_step_follow_flag_visibility(
        self,
        _name: str,
        flags: tuple[WorkFlag, ...],
        linked: list[int],
        hidden: bool,
        title: str,
        labels: list[str],
    ) -> None:
        result = thread(flags, linked_flag_ids=linked, has_hidden_flags=hidden)

        assert (current(result).title, next_labels(result)) == (title, labels)

    def test_hidden_flags_leave_no_flag_item_or_values_in_the_thread(self) -> None:
        result = thread((), linked_flag_ids=[], has_hidden_flags=True)

        step = current(result)
        assert (step.item, step.facts, step.description) == (
            None,
            [],
            "Behind flags you cannot see. You do not have access to the flags of this release.",
        )

    @parameterized.expand(
        [
            ("behind_a_flag", (PARTIAL,), (), ["metric", "experiment", "early-access", "survey"]),
            ("behind_a_flag_with_a_linked_survey", (PARTIAL,), (SURVEY,), ["metric", "experiment", "early-access"]),
            ("rolled_out", (flag(),), (), ["metric", "broadcast", "survey"]),
            ("rolled_out_with_a_linked_survey", (flag(),), (SURVEY,), ["metric", "broadcast"]),
            ("planned", (), (), ["metric"]),
            ("ended", (ARCHIVED,), (), ["metric"]),
        ]
    )
    def test_suggests_ideas_that_fit_the_stage(
        self, _name: str, flags: tuple[WorkFlag, ...], surveys: tuple[LinkedSurveyDTO, ...], keys: list[str]
    ) -> None:
        assert alongside_keys(thread(flags, surveys=surveys)) == keys

    @parameterized.expand(
        [
            (
                "planned",
                (),
                [
                    ("link-flag", "You need editor access to feature flags to link a flag."),
                    ("create-flag", "You need editor access to feature flags to create a flag."),
                    ("metric", "You need editor access to feature flags to add a metric."),
                ],
            ),
            (
                "behind_a_flag",
                (PARTIAL,),
                [
                    ("schedule-rollout:1", None),
                    ("widen-rollout:1", None),
                    ("metric", "You need editor access to feature flags to add a metric."),
                    ("experiment", None),
                    ("early-access", None),
                    ("survey", "You need editor access to feature flags to add a survey."),
                ],
            ),
        ]
    )
    def test_a_viewer_who_cannot_edit_sees_the_edit_options_gated(
        self, _name: str, flags: tuple[WorkFlag, ...], options: list[tuple[str, str | None]]
    ) -> None:
        result = thread(flags, can_edit=False)

        assert [(option.key, option.gate) for option in current(result).options] == options

    def test_a_linked_broadcast_stops_the_broadcast_suggestion_and_starts_a_line(self) -> None:
        result = thread((flag(),), broadcasts=(BROADCAST,), surveys=(SURVEY,))

        lines = current(result).alongside
        assert "broadcast" not in alongside_keys(result)
        assert [(line.key, line.steps[0].item.href if line.steps[0].item else None) for line in lines] == [
            (f"survey:{SURVEY_ID}", f"/surveys/{SURVEY_ID}"),
            (f"broadcast:{BROADCAST_ID}", f"/broadcasts/{BROADCAST_ID}"),
        ]
        assert lines[0].steps[0].facts[0].value == "Running"

    def test_the_broadcast_suggestion_links_the_new_broadcast_to_the_release(self) -> None:
        option = next(option for option in current(thread((flag(),))).options if option.key == "broadcast")

        assert option.helper.run.to == (
            f"/broadcasts/new?name=Quiet%20theme&source=release&source_record=release%3A{RELEASE_ID}"
        )

    def test_an_archived_early_access_feature_does_not_bring_back_the_early_access_suggestion(self) -> None:
        result = thread((PARTIAL,), early_access_features=(early_access("archived"),))

        assert "early-access" not in alongside_keys(result)

    def test_counts_only_flags_open_to_all_users_toward_the_flags_that_reach_everyone(self) -> None:
        result = thread((flag(), flag(flag_id=2, key="quiet-theme-paid", property_count=1)))

        assert current(result).description == "1 of 2 flags reach everyone"

    @parameterized.expand(
        [
            ("draft", (experiment("draft"),), ["Launch the experiment"], None, "/experiments/7"),
            (
                "running_two_weeks",
                (experiment("running", start_date=NOW - timedelta(days=12)),),
                ["Review the results"],
                None,
                "/experiments/7",
            ),
            (
                "running_a_few_days",
                (experiment("running"),),
                ["Review the results"],
                "Check the results around 1 Dec, when it has two weeks of data.",
                "/experiments/7",
            ),
            ("paused", (experiment("paused"),), ["Resume or end the experiment"], None, "/experiments/7"),
            ("ended_without_a_result", (experiment("stopped"),), ["Record the result"], None, "/experiments/7"),
        ]
    )
    def test_experiment_rules_open_the_experiment(
        self,
        _name: str,
        experiments: tuple[WorkExperiment, ...],
        labels: list[str],
        gate: str | None,
        href: str,
    ) -> None:
        result = thread((PARTIAL,), experiments=experiments)

        option = current(result).options[0]
        assert (current(result).title, next_labels(result), option.gate, option.helper.run.to) == (
            "Experiment",
            labels,
            gate,
            href,
        )
        assert option.helper.mode == WorkHelperMode.OPENS

    def test_an_ended_experiment_with_a_winner_asks_to_schedule_the_rollout_in_place(self) -> None:
        result = thread((PARTIAL,), experiments=(experiment("stopped", conclusion="won"),))

        schedule = current(result).options[0]
        assert (schedule.label, schedule.helper.mode, schedule.helper.run.type, schedule.helper.run.params) == (
            "Roll out the winner",
            WorkHelperMode.IN_PLACE,
            WorkRunType.ACTION,
            {"flag_id": 1},
        )
        assert (schedule.helper.run.action_id, schedule.helper.run_label) == ("schedule_rollout", "Schedule rollout")
        assert [step.chosen_label for step in result.line.steps[:-1]] == ["Link a feature flag", "Measure the impact"]

    def test_a_partial_rollout_asks_to_roll_out_to_more_users(self) -> None:
        result = thread((PARTIAL,))

        assert next_labels(result) == ["Roll out to more users", "Widen the release conditions of quiet-theme"]
        assert current(result).description == "50% of all users"

    @parameterized.expand(
        [
            ("draft", "Launch early access", "Behind a flag"),
            ("concept", "Open the beta", "Behind a flag"),
            ("beta", "Move to general availability", "Early access"),
        ]
    )
    def test_early_access_rules_move_the_feature_on(self, stage: str, label: str, title: str) -> None:
        result = thread((PARTIAL,), early_access_features=(early_access(stage),))

        assert (current(result).title, next_labels(result)[0]) == (title, label)
        assert current(result).options[0].helper.run.to == f"/early_access_features/{EARLY_ACCESS_ID}"

    def test_an_experiment_the_viewer_cannot_see_holds_back_the_next_step(self) -> None:
        result = thread((PARTIAL,), incomplete_flag_ids=frozenset({1}))

        assert (next_labels(result), alongside_keys(result)) == ([], ["metric"])

    def test_an_ended_release_is_not_in_flight_and_offers_nothing_next(self) -> None:
        result = thread((ARCHIVED,))

        assert (current(result).title, next_labels(result)) == ("Ended", [])
        assert [step.title for step in result.line.steps] == ["Planned", "Behind a flag", "Ended"]

    def test_step_keys_name_their_stage_and_item(self) -> None:
        result = thread((PARTIAL,), experiments=(experiment("running"),))

        assert [step.key for step in result.line.steps] == [
            f"release:{RELEASE_ID}:planned",
            f"release:{RELEASE_ID}:flag:feature_flag:1",
            f"release:{RELEASE_ID}:testing:experiment:7",
        ]

    @parameterized.expand(
        [
            ("ended", (ARCHIVED,), False),
            ("one_of_two_flags_archived", (ARCHIVED, flag(flag_id=2, key="quiet-theme-eu", rollout=50)), True),
            ("rolled_out", (flag(),), True),
            ("planned", (), True),
        ]
    )
    def test_in_flight_releases_are_the_ones_that_have_not_ended(
        self, _name: str, flags: tuple[WorkFlag, ...], expected: bool
    ) -> None:
        release_thread_facts = ReleaseWorkFacts(
            release=ReleaseDTO(
                id=RELEASE_ID,
                name="Quiet theme",
                description="",
                owner=None,
                feature_flag_ids=[item.id for item in flags],
                has_hidden_flags=False,
                broadcast_ids=[],
                broadcasts=[],
                survey_ids=[],
                surveys=[],
                insight_ids=[],
                insights=[],
                metric_insight_ids=[],
                metric_goals=[],
                created_at=NOW,
            ),
            details=ReleaseFlagDetails(
                flags=flags, experiments=(), early_access_features=(), incomplete_flag_ids=frozenset()
            ),
            now=NOW,
            can_edit=True,
        )

        assert is_in_flight(release_thread_facts) is expected
