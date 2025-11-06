from datetime import datetime
from textwrap import dedent

import pytest

from braintrust import EvalCase

from posthog.schema import (
    AssistantFunnelsEventsNode,
    AssistantFunnelsExclusionEventsNode,
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
    NodeKind,
)

from products.enterprise.backend.hogai.graph.funnels.toolkit import FUNNEL_SCHEMA

from ..base import MaxPublicEval
from ..scorers import PlanAndQueryOutput, PlanCorrectness, QueryAndPlanAlignment, QueryKindSelection, TimeRangeRelevancy


@pytest.mark.django_db
async def eval_funnel(call_root_for_insight_generation, pytestconfig):
    await MaxPublicEval(
        experiment_name="funnel",
        task=call_root_for_insight_generation,
        scores=[
            QueryKindSelection(expected=NodeKind.FUNNELS_QUERY),
            PlanCorrectness(
                query_kind=NodeKind.FUNNELS_QUERY,
                evaluation_criteria="""
1. A plan must define at least two series in the sequence, but it is not required to define any filters, exclusion steps, or a breakdown.
2. Compare events, properties, math types, and property values of 'expected plan' and 'output plan'. Do not penalize if the actual output does not include a timeframe unless specified in the 'expected plan'.
3. Check if the combination of events, properties, and property values in 'output plan' can answer the user's question according to the 'expected plan'.
4. Check if the math types in 'output plan' match those in 'expected plan.' If the aggregation type is specified by a property, user, or group in 'expected plan', the same property, user, or group must be used in 'generated plan'.
5. If 'expected plan' contains exclusion steps, check if 'output plan' contains those, and heavily penalize if the exclusion steps are not present or different.
6. If 'expected plan' contains a breakdown, check if 'output plan' contains a similar breakdown, and heavily penalize if the breakdown is not present or different. Plans may only have one breakdown.
7. Heavily penalize if the 'output plan' contains any excessive output not present in the 'expected plan'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.
""",
            ),
            QueryAndPlanAlignment(
                query_kind=NodeKind.FUNNELS_QUERY,
                json_schema=FUNNEL_SCHEMA,
                evaluation_criteria="""
1. Series sequence: Verify that the funnel steps in the query's `series` array match the sequence order and events specified in the plan. The order must be preserved if funnel steps are set to be sequential (ordered).
2. Event names: Ensure each funnel step uses the exact event name specified in the plan for that step position.
3. Property filters: Check that event properties and filters from the plan are correctly implemented for each step:
   - Property names, values, and operators must match exactly
   - Multiple property values should be represented as arrays in the `value` field
   - Filter types (event, person, group) must be correct
   - Properties should be applied to the correct funnel step
4. Math operations: Verify that math aggregations for each step match the plan (though most funnel steps use `math: null` for simple event counting).
5. Exclusions: For exclusion steps mentioned in the plan:
   - Exclusion events must be present in the `funnelsFilter.exclusions` array
   - Start and end step indices (`funnelFromStep`, `funnelToStep`) must match the plan specification
   - Exclusion event names must be exact
6. Breakdown implementation: Verify breakdown configuration matches the plan:
   - Breakdown property name must match exactly
   - Breakdown type (event, person, group) must be correct
   - Only one breakdown should be present (funnels support single breakdown only)
7. Funnel configuration: Check core funnel settings align with typical defaults:
   - `funnelOrderType` should typically be "ordered" unless plan specifies otherwise
   - `funnelStepReference` should be "total" for standard conversion funnels
   - `funnelVizType` should be "steps" for standard funnel visualization
8. Time window: Verify funnel time window settings when specified in the plan:
   - `funnelWindowInterval` and `funnelWindowIntervalUnit` should match plan requirements
   - Default to reasonable values (e.g., 14 days) when not specified
9. Aggregation: Check if group aggregation is correctly set when plan specifies group-based funnels (`aggregation_group_type_index`).
10. Missing implementation: Heavily penalize when key plan elements are missing (e.g., missing exclusions, wrong sequence order, incorrect breakdown).
11. Unnecessary fields: Penalize inclusion of fields not mentioned in the plan or that don't align with the funnel intent.
12. Schema compliance: Ensure all query fields conform to the FUNNEL_SCHEMA structure and constraints.
""",
            ),
            TimeRangeRelevancy(query_kind=NodeKind.FUNNELS_QUERY),
        ],
        data=[
            EvalCase(
                input="Conversion from page view to sign up",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelAggregateByHogQL="properties.$session_id",
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(
                                event="$pageview",
                                math=None,
                            ),
                            AssistantFunnelsEventsNode(
                                event="signed_up",
                                math=None,
                            ),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="what was the conversion from a page view to sign up?",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="What was the conversion from uploading a file to downloading it from Chrome and Safari in the last 30d?",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. uploaded_file
    - property filter 1:
        - entity: event
        - property name: $browser
        - property type: String
        - operator: equals
        - property value: Chrome, Safari
2. downloaded_file
    - property filter 1:
        - entity: event
        - property name: $browser
        - property type: String
        - operator: equals
        - property value: Chrome, Safari
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            exclusions=[], funnelOrderType="ordered", funnelStepReference="total", funnelVizType="steps"
                        ),
                        series=[
                            AssistantFunnelsEventsNode(
                                event="uploaded_file",
                                math=None,
                                properties=[
                                    {
                                        "key": "$browser",
                                        "value": ["Chrome", "Safari"],
                                        "operator": "exact",
                                        "type": "event",
                                    },
                                ],
                            ),
                            AssistantFunnelsEventsNode(
                                event="downloaded_file",
                                math=None,
                                properties=[
                                    {
                                        "key": "$browser",
                                        "value": ["Chrome", "Safari"],
                                        "operator": "exact",
                                        "type": "event",
                                    },
                                ],
                            ),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="What was the conversion from uploading a file to downloading it in the last 30d excluding users that invited a team member?",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. uploaded_file
2. downloaded_file

Exclusions:
- invited_team_member
    - start index: 0
    - end index: 1
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            exclusions=[
                                AssistantFunnelsExclusionEventsNode(
                                    event="invited_team_member",
                                    funnelFromStep=0,
                                    funnelToStep=1,
                                )
                            ],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="uploaded_file", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="downloaded_file", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="Show a conversion from uploading a file to downloading it segmented by a browser",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. uploaded_file
2. downloaded_file

Breakdown by:
- entity: event
- property name: $browser
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter={"breakdown": "$browser", "breakdown_type": "event"},
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="uploaded_file", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="downloaded_file", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="What was the conversion from a sign up to a paying customer on the personal-pro plan?",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. signed_up
2. paid_bill
    - property filter 1:
        - entity: event
        - property name: plan
        - property type: String
        - operator: equals
        - property value: personal/pro
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                            AssistantFunnelsEventsNode(
                                event="paid_bill",
                                math=None,
                                properties=[
                                    {"key": "plan", "value": "personal/pro", "operator": "exact", "type": "event"}
                                ],
                            ),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="What's our sign-up funnel?",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="what was the conversion from a page view to sign up for event time before 2024-01-01?",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up

Time period: before 2024-01-01
Granularity: day
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "2023-12-01", "date_to": "2024-01-01"},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,  # Default, plan doesn't specify interval length
                            funnelWindowIntervalUnit="day",  # From plan
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="conversion from a page view to a sign up for yesterday",
                expected=PlanAndQueryOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for yesterday",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-1d", "date_to": "dStart"},  # "yesterday"
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="conversion from a page view to a sign up for the last 1 week",
                expected=PlanAndQueryOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for the last 1 week",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-7d"},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="conversion from a page view to a sign up for the last 1 month",
                expected=PlanAndQueryOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for the last 1 month",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-1m"},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="conversion from a page view to a sign up for the last 80 days",
                expected=PlanAndQueryOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for the last 80 days",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-80d"},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="conversion from a page view to a sign up for the last 6 months",
                expected=PlanAndQueryOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: for the last 6 months",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-6m"},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="conversion from a page view to a sign up from 2020 to 2025",
                expected=PlanAndQueryOutput(
                    plan="Sequence:\\n1. $pageview\\n2. signed_up\\n\\nTime period: from 2020 to 2025",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "2020-01-01", "date_to": "2025-12-31"},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="conversion from a page view to a sign up",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. $pageview
2. signed_up

Time period: last 30 days
Time interval: day
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-30d"},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",  # from "Time interval: day"
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="what is the conversion rate from a page view to sign up for users with name John?",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. $pageview
- property filter 1
    - person
    - name
    - equals
    - John
2. signed_up
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={"date_from": "-30d", "date_to": None},
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(
                                event="$pageview",
                                math=None,
                                properties=[{"key": "name", "value": "John", "operator": "exact", "type": "person"}],
                            ),
                            AssistantFunnelsEventsNode(event="signed_up", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            EvalCase(
                input="what is the conversion rate from a page view to a next page view in this January?",
                expected=PlanAndQueryOutput(
                    plan="""
Sequence:
1. $pageview
2. $pageview

Time period: this January
""",
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={
                            "date_from": f"{datetime.now().year}-01-01",
                            "date_to": f"{datetime.now().year}-01-31",
                        },
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            # Should include the aggregation by session
            EvalCase(
                input="what is the conversion rate from a page view to a next page view in this January aggregated by session?",
                expected=PlanAndQueryOutput(
                    plan=dedent("""
                        Sequence:
                        1. $pageview
                        2. $pageview

                        Time period: this January
                    """),
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={
                            "date_from": f"{datetime.now().year}-01-01",
                            "date_to": f"{datetime.now().year}-01-31",
                        },
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                            funnelAggregateByHogQL="properties.$session_id",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            # Should include the aggregation by user
            EvalCase(
                input="what is the conversion rate from a page view to a next page view in this January aggregated by user?",
                expected=PlanAndQueryOutput(
                    plan=dedent("""
                        Sequence:
                        1. $pageview
                        2. $pageview

                        Time period: this January
                    """),
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=None,
                        breakdownFilter=None,
                        dateRange={
                            "date_from": f"{datetime.now().year}-01-01",
                            "date_to": f"{datetime.now().year}-01-31",
                        },
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                        ],
                    ),
                ),
            ),
            # Should aggregate by unique accounts (group analytics)
            EvalCase(
                input="what is the conversion rate from a page view to a next page view in this January aggregated by unique accounts?",
                expected=PlanAndQueryOutput(
                    plan=dedent("""
                        Sequence:
                        1. $pageview
                        2. $pageview

                        Time period: this January
                    """),
                    query=AssistantFunnelsQuery(
                        aggregation_group_type_index=0,
                        breakdownFilter=None,
                        dateRange={
                            "date_from": f"{datetime.now().year}-01-01",
                            "date_to": f"{datetime.now().year}-01-31",
                        },
                        filterTestAccounts=True,
                        funnelsFilter=AssistantFunnelsFilter(
                            binCount=None,
                            exclusions=[],
                            funnelOrderType="ordered",
                            funnelStepReference="total",
                            funnelVizType="steps",
                            funnelWindowInterval=14,
                            funnelWindowIntervalUnit="day",
                        ),
                        series=[
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                            AssistantFunnelsEventsNode(event="$pageview", math=None, properties=None),
                        ],
                    ),
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )
