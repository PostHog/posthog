import logging

import pytest

from braintrust import EvalCase, Score
from braintrust_core.score import Scorer
from deepdiff import DeepDiff

from posthog.schema import (
    DurationType,
    EventPropertyFilter,
    FilterLogicalOperator,
    MaxInnerUniversalFiltersGroup,
    MaxOuterUniversalFiltersGroup,
    MaxRecordingUniversalFilters,
    PersonPropertyFilter,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingOrder,
    RecordingOrderDirection,
)

from products.enterprise.backend.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from products.enterprise.backend.models.assistant import Conversation
from products.replay.backend.max_tools import SessionReplayFilterOptionsGraph
from products.replay.backend.prompts import USER_FILTER_OPTIONS_PROMPT

from ...base import MaxPublicEval

logger = logging.getLogger(__name__)

DUMMY_CURRENT_FILTERS = MaxRecordingUniversalFilters(
    date_from="-7d",
    date_to=None,
    duration=[
        RecordingDurationFilter(key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0)
    ],
    filter_group=MaxOuterUniversalFiltersGroup(
        type=FilterLogicalOperator.AND_,
        values=[MaxInnerUniversalFiltersGroup(type=FilterLogicalOperator.AND_, values=[])],
    ),
    filter_test_accounts=True,
    order=RecordingOrder.START_TIME,
    order_direction=RecordingOrderDirection.DESC,
)


@pytest.fixture
def call_search_session_recordings(demo_org_team_user):
    graph = SessionReplayFilterOptionsGraph(demo_org_team_user[1], demo_org_team_user[2]).compile_full_graph(
        checkpointer=DjangoCheckpointer()
    )

    async def callable(change: str) -> dict:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

        # Convert filters to JSON string and use test-specific prompt
        filters_json = DUMMY_CURRENT_FILTERS.model_dump_json(indent=2)

        graph_input = {
            "change": USER_FILTER_OPTIONS_PROMPT.format(change=change, current_filters=filters_json),
            "output": None,
        }

        result = await graph.ainvoke(graph_input, config={"configurable": {"thread_id": conversation.id}})
        return result

    return callable


class FilterGenerationCorrectness(Scorer):
    """Score the correctness of generated filters."""

    def _name(self):
        return "filter_generation_correctness"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        try:
            actual_filters = MaxRecordingUniversalFilters.model_validate(output["output"])
        except Exception as e:
            logger.exception(f"Error parsing filters: {e}")
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid filter structure"})

        # Convert both objects to dict for deepdiff comparison
        actual_dict = actual_filters.model_dump()
        expected_dict = expected.model_dump()

        # Use deepdiff to find differences
        diff = DeepDiff(expected_dict, actual_dict, ignore_order=True, report_repetition=True)

        if not diff:
            return Score(name=self._name(), score=1.0, metadata={"reason": "Perfect match"})

        # Calculate score based on number of differences
        total_fields = len(expected_dict.keys())
        changed_fields = (
            len(diff.get("values_changed", {}))
            + len(diff.get("dictionary_item_added", set()))
            + len(diff.get("dictionary_item_removed", set()))
        )

        score = max(0.0, (total_fields - changed_fields) / total_fields)

        return Score(
            name=self._name(),
            score=score,
            metadata={
                "differences": str(diff),
                "total_fields": total_fields,
                "changed_fields": changed_fields,
                "reason": f"Found {changed_fields} differences out of {total_fields} fields",
            },
        )


class AskUserForHelp(Scorer):
    """Score the correctness of the ask_user_for_help tool."""

    def _name(self):
        return "ask_user_for_help_scorer"

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if "output" not in output or output["output"] is None:
            if (
                "intermediate_steps" in output
                and len(output["intermediate_steps"]) > 0
                and output["intermediate_steps"][-1][0].tool == "ask_user_for_help"
            ):
                return Score(
                    name=self._name(), score=1, metadata={"reason": "LLM returned valid ask_user_for_help response"}
                )
            else:
                return Score(
                    name=self._name(),
                    score=0,
                    metadata={"reason": "LLM did not return valid ask_user_for_help response"},
                )
        else:
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned a filter"})


class DateTimeFilteringCorrectness(Scorer):
    """Score the correctness of the date time filtering."""

    def _name(self):
        return "date_time_filtering_correctness"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        try:
            actual_filters = MaxRecordingUniversalFilters.model_validate(output["output"])
        except Exception as e:
            logger.exception(f"Error parsing filters: {e}")
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid filter structure"})

        if actual_filters.date_from == expected.date_from and actual_filters.date_to == expected.date_to:
            return Score(name=self._name(), score=1.0, metadata={"reason": "LLM returned valid date time filters"})
        elif actual_filters.date_from == expected.date_from:
            return Score(
                name=self._name(),
                score=0.5,
                metadata={"reason": "LLM returned valid date_from but did not return valid date_to"},
            )
        elif actual_filters.date_to == expected.date_to:
            return Score(
                name=self._name(),
                score=0.5,
                metadata={"reason": "LLM returned valid date_to but did not return valid date_from"},
            )
        else:
            return Score(name=self._name(), score=0.0, metadata={"reason": "LLM returned invalid date time filters"})


@pytest.mark.django_db
async def eval_tool_search_session_recordings(call_search_session_recordings, pytestconfig):
    await MaxPublicEval(
        experiment_name="tool_search_session_recordings",
        task=call_search_session_recordings,
        scores=[FilterGenerationCorrectness(), DateTimeFilteringCorrectness()],
        data=[
            # Test basic filter generation for mobile devices
            EvalCase(
                input="show me recordings of users that were using a mobile device (use events)",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$device_type",
                                        type="event",
                                        value=["Mobile"],
                                        operator=PropertyOperator.EXACT,
                                    )
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test date range filtering
            EvalCase(
                input="Show recordings from the last 2 hours",
                expected=MaxRecordingUniversalFilters(
                    date_from="-2h",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[MaxInnerUniversalFiltersGroup(type=FilterLogicalOperator.AND_, values=[])],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test location filtering
            EvalCase(
                input="Show recordings for users located in the US",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    PersonPropertyFilter(
                                        key="$geoip_country_code",
                                        type="person",
                                        value=["US"],
                                        operator=PropertyOperator.EXACT,
                                    )
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test browser-specific filtering
            EvalCase(
                input="Show recordings from users that were using a browser in English",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    PersonPropertyFilter(
                                        key="$browser_language",
                                        type="person",
                                        value=["EN-en"],
                                        operator=PropertyOperator.EXACT,
                                    )
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            EvalCase(
                input="Show me recordings from chrome browsers",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$browser",
                                        type="event",
                                        value=["Chrome"],
                                        operator=PropertyOperator.EXACT,
                                    )
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test user behavior filtering
            EvalCase(
                input="Show recordings where users visited the posthog.com/checkout_page",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$current_url",
                                        type="event",
                                        value=["posthog.com/checkout_page"],
                                        operator=PropertyOperator.ICONTAINS,
                                    )
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test session duration filtering
            EvalCase(
                input="Show recordings longer than 5 minutes",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=300.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[MaxInnerUniversalFiltersGroup(type=FilterLogicalOperator.AND_, values=[])],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test user action
            EvalCase(
                input="Show recordings from users that performed a billing action",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="paid_bill",
                                        type="event",
                                        value=None,
                                        operator=PropertyOperator.IS_SET,
                                    )
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test page-specific filtering
            EvalCase(
                input="Show recordings from users who visited the pricing page",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$pathname",
                                        type="event",
                                        value=["/pricing/"],
                                        operator=PropertyOperator.ICONTAINS,
                                    )
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test conversion funnel filtering
            EvalCase(
                input="Show recordings from users who completed the signup flow",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="signup_completed",
                                        type="event",
                                        value=None,
                                        operator=PropertyOperator.IS_SET,
                                    )
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test device and browser combination
            EvalCase(
                input="Show recordings from mobile Safari users",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$device_type",
                                        type="event",
                                        value=["Mobile"],
                                        operator=PropertyOperator.EXACT,
                                    ),
                                    EventPropertyFilter(
                                        key="$browser",
                                        type="event",
                                        value=["Safari"],
                                        operator=PropertyOperator.EXACT,
                                    ),
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            # Test time-based filtering
            EvalCase(
                input="Show recordings from yesterday",
                expected=DUMMY_CURRENT_FILTERS.model_copy(update={"date_from": "-1d", "date_to": "-1d"}),
            ),
            EvalCase(
                input="Show me recordings since the 1st of August",
                expected=DUMMY_CURRENT_FILTERS.model_copy(update={"date_from": "2025-08-01T00:00:00:000"}),
            ),
            EvalCase(
                input="Show me recordings until the 31st of August",
                expected=DUMMY_CURRENT_FILTERS.model_copy(update={"date_to": "2025-08-31T23:59:59:999"}),
            ),
            EvalCase(
                input="Show me recordings from the 1st of September to the 31st of September",
                expected=DUMMY_CURRENT_FILTERS.model_copy(
                    update={"date_from": "2025-09-01T00:00:00:000", "date_to": "2025-09-30T23:59:59:999"}
                ),
            ),
            EvalCase(
                input="Show me recordings from the 1st of September to the 1st of September",
                expected=DUMMY_CURRENT_FILTERS.model_copy(
                    update={"date_from": "2025-09-01T00:00:00:000", "date_to": "2025-09-01T23:59:59:999"}
                ),
            ),
            EvalCase(
                input="show me recordings of users who signed up on mobile",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$device_type",
                                        type="event",
                                        value=["Mobile"],
                                        operator=PropertyOperator.EXACT,
                                    )
                                ],
                            )
                        ],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.START_TIME,
                ),
            ),
            EvalCase(
                input="Show recordings in an ascending order by duration",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION, operator=PropertyOperator.GT, type="recording", value=60.0
                        )
                    ],
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[MaxInnerUniversalFiltersGroup(type=FilterLogicalOperator.AND_, values=[])],
                    ),
                    filter_test_accounts=True,
                    order=RecordingOrder.DURATION,
                    order_direction=RecordingOrderDirection.ASC,
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_tool_search_session_recordings_ask_user_for_help(call_search_session_recordings, pytestconfig):
    await MaxPublicEval(
        experiment_name="tool_search_session_recordings_ask_user_for_help",
        task=call_search_session_recordings,
        scores=[AskUserForHelp()],
        data=[
            EvalCase(input="Tell me something about insights", expected="clarify"),
        ],
        pytestconfig=pytestconfig,
    )
