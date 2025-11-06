from typing import Optional
from uuid import uuid4

import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase

from posthog.schema import AssistantMessage, HumanMessage

from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.enterprise.backend.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from products.enterprise.backend.hogai.graph.deep_research.graph import DeepResearchAssistantGraph
from products.enterprise.backend.hogai.graph.deep_research.types import DeepResearchNodeName, DeepResearchState
from products.enterprise.backend.models.assistant import Conversation

from ...base import MaxPublicEval


class HasCorrectSections(LLMClassifier):
    """Binary check: Does the onboarding message contain appropriate sections (up to 4)?"""

    def __init__(self, **kwargs):
        super().__init__(
            name="has_correct_sections",
            prompt_template="""Evaluate if the onboarding message has an appropriate number of well-organized sections.

CRITERIA FOR PASS:
1. Contains 1-4 main sections (count ## headers starting with numbers)
2. Each section uses format: "## N. Section Title" where N is 1, 2, 3, or 4
3. Sections are logically organized and non-redundant
4. If fewer than 4 sections, remaining content must be substantive enough to warrant separate sections

CRITERIA FOR FAIL:
- Contains 0 sections or more than 4 sections
- Section headers don't follow "## N. Title" format
- Sections are repetitive or poorly organized
- Content artificially split into too many thin sections

EXAMPLE PASS:
## 1. Core Objective
## 2. Scope & Timeline
## 3. Success Metrics

EXAMPLE FAIL:
## 1. Objective
## 2. Goals
## 3. Targets
## 4. Metrics
## 5. Timeline
(Too many sections, some redundant)

<actual_output>{{output}}</actual_output>

Count the main sections (## headers with numbers) and evaluate organization:
- pass: 1-4 well-organized, properly formatted sections
- fail: Wrong number of sections or poor organization""",
            choice_scores={
                "pass": 1.0,
                "fail": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


class IsConciseAndFocused(LLMClassifier):
    """Binary check: Is the onboarding message concise and focused?"""

    def __init__(self, **kwargs):
        super().__init__(
            name="is_concise_and_focused",
            prompt_template="""Evaluate if the onboarding message is appropriately concise and focused.

CRITERIA FOR PASS:
1. Each section contains exactly 1-2 bullet points (count • or * items per section)
2. Each bullet point asks compound questions that gather multiple related insights efficiently
3. Total word count is reasonable (typically 150-300 words for the entire message)
4. No verbose explanations, lengthy preambles, or unnecessary context
5. Questions are direct and actionable

CRITERIA FOR FAIL:
- Any section has more than 2 bullet points
- Questions are overly granular instead of efficiently compound
- Excessive word count or verbose language
- Long explanatory text before or between questions
- Questions lack focus or efficiency

EXAMPLE EFFICIENT COMPOUND QUESTION:
• What specific user behavior are you trying to understand, and what business decision will this research inform?

EXAMPLE INEFFICIENT (TOO GRANULAR):
• What user behavior interests you?
• Why do you want to understand this behavior?
• What will you do with this information?

<actual_output>{{output}}</actual_output>

Count bullet points per section and evaluate question efficiency:
- pass: 1-2 focused bullet points per section with efficient compound questions
- fail: Too many bullet points per section or inefficient questioning""",
            choice_scores={
                "pass": 1.0,
                "fail": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


class CoversEssentialTopics(LLMClassifier):
    """Binary check: Does the onboarding message cover all essential research topics?"""

    def __init__(self, **kwargs):
        super().__init__(
            name="covers_essential_topics",
            prompt_template="""Evaluate if the onboarding message covers essential research topics appropriately for the context.

ESSENTIAL RESEARCH AREAS (must cover what's not already provided by user):
1. Core Objective: What specific question/problem they're solving and why
2. Scope & Boundaries: Which users/timeframe/features to analyze
3. Success Metrics: How they'll measure success and what "good" looks like
4. Context & Constraints: Recent changes, hypotheses, or external factors

CRITERIA FOR PASS:
- Covers ALL essential areas that weren't comprehensively addressed in user input
- Each covered area has specific, actionable questions (not generic ones)
- Questions would actually help gather the missing information needed
- If user provided detailed context in some areas, those areas can be covered more lightly or skipped

CRITERIA FOR FAIL:
- Missing coverage of essential areas that user didn't provide
- Questions are too generic ("What are your goals?" vs "What specific conversion rate improvement would be meaningful?")
- Asks about information the user already provided in detail
- Areas covered but questions won't elicit useful specific information

EXAMPLE SPECIFIC QUESTIONS:
• "What specific user behavior are you trying to understand, and what business decision will this research inform?"
• "What's your current conversion rate, and what improvement would be meaningful?"

EXAMPLE GENERIC QUESTIONS (FAIL):
• "What are your objectives?"
• "What metrics matter to you?"

<actual_output>{{output}}</actual_output>

Assess topic coverage and question specificity for this context:
- pass: Covers all needed essential areas with specific, actionable questions
- fail: Missing essential areas or questions are too generic/redundant""",
            choice_scores={
                "pass": 1.0,
                "fail": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


@pytest.fixture
def call_deep_research_onboarding():
    """Fixture to call DeepResearchOnboardingNode with a parametrized input."""

    async def callable(input: str) -> Optional[AssistantMessage]:
        _, team, user = await database_sync_to_async(User.objects.bootstrap)(
            organization_name="TestOrg", email=f"{uuid4()}@example.com", password=None
        )

        conversation = await Conversation.objects.acreate(team=team, user=user)

        # Minimal graph with just the onboarding node
        graph_builder = DeepResearchAssistantGraph(team=team, user=user)
        graph_builder.add_onboarding_node(
            node_map={
                "onboarding": DeepResearchNodeName.ONBOARDING,
                "planning": DeepResearchNodeName.END,
                "continue": DeepResearchNodeName.END,
            }
        )
        # Add edge from ONBOARDING to END
        graph_builder.add_edge(DeepResearchNodeName.ONBOARDING, DeepResearchNodeName.END)
        graph = graph_builder.compile(checkpointer=DjangoCheckpointer())
        raw_state = await graph.ainvoke(
            DeepResearchState(messages=[HumanMessage(content=input)]),
            {"configurable": {"thread_id": conversation.id}},
        )

        state = DeepResearchState.model_validate(raw_state)
        if not state.messages:
            return None
        # Get the last assistant message
        assistant_messages = [m for m in state.messages if isinstance(m, AssistantMessage)]
        if not assistant_messages:
            return None
        return assistant_messages[-1]

    return callable


@pytest.mark.django_db
async def eval_deep_research_onboarding(call_deep_research_onboarding, pytestconfig):
    await MaxPublicEval(
        experiment_name="deep_research_onboarding",
        task=call_deep_research_onboarding,
        scores=[
            HasCorrectSections(),
            IsConciseAndFocused(),
            CoversEssentialTopics(),
        ],
        data=[
            # Case: Generic research request
            EvalCase(
                input="I want to understand user behavior",
                expected="""## 1. Core Objective
* What specific user behavior are you trying to understand - is it about adoption, retention, engagement patterns, or something else?
* What business decision or action will this research inform?

## 2. Scope & Boundaries
* Which user segments or cohorts should we focus on (e.g., new vs. existing, paid vs. free, specific industries)?
* What time period matters most - recent trends, seasonal patterns, or long-term evolution?

## 3. Success Metrics
* What are your key performance indicators, and what would "good" look like for each?
* Do you have any benchmarks or targets we should compare against?

## 4. Context & Hypotheses
* Have you noticed any recent changes or patterns that triggered this research?
* Any working theories about what might be driving the behavior you're seeing?""",
            ),
            # Case: Specific feature analysis
            EvalCase(
                input="We need to analyze our checkout funnel performance",
                expected="""## 1. Core Objective
* Are you looking to identify where users drop off, understand why they abandon, or optimize conversion rates?
* Is this about fixing a specific problem or general optimization?

## 2. Scope & Focus
* Should we analyze all checkout attempts or focus on specific user segments (mobile vs. desktop, new vs. returning)?
* What timeframe is most relevant - recent performance, comparison to last quarter, or historical trends?

## 3. Success Metrics
* What's your current conversion rate, and what improvement would be meaningful?
* Beyond conversion, are there other metrics like cart value or time-to-purchase that matter?

## 4. Context & Changes
* Have you recently made changes to the checkout flow or noticed any shifts in performance?
* Any hypotheses about friction points or competitor insights influencing your analysis?""",
            ),
            # Case: Another specific request
            EvalCase(
                input="Help me understand what's driving our growth",
                expected="""## 1. Core Objective
* Are you focused on user acquisition, activation, retention, or revenue growth specifically?
* What growth challenge or opportunity are you trying to address?

## 2. Scope & Segments
* Which products, features, or user segments are most critical to analyze?
* What time period should we examine - recent acceleration, month-over-month trends, or year-over-year comparison?

## 3. Success Metrics
* What are your primary growth KPIs, and what targets are you aiming for?
* How do you currently define and measure "growth" - MAU, revenue, engagement, or something else?

## 4. Context & Hypotheses
* What recent initiatives, campaigns, or market changes might be influencing growth?
* Any initial thoughts on what's working well or holding you back?""",
            ),
            # Case: Retention analysis research request
            EvalCase(
                input="We're seeing user churn and need to understand why",
                expected="""## 1. Core Objective
* Are you looking to identify who's churning, understand why they leave, or find early warning signals?
* What specific retention improvements would have the biggest impact on your business?

## 2. Scope & Definition
* How do you define churn (last activity, subscription cancellation, etc.) and which user cohorts are most affected?
* Should we focus on recent churn patterns or analyze longer-term retention curves?

## 3. Success Metrics
* What's your current retention rate, and what improvement would be significant?
* Are there specific retention milestones (day 1, week 1, month 1) that matter most?

## 4. Context & Patterns
* Have you noticed any patterns in who churns or when (after specific events, time periods)?
* Any recent product changes, competitive pressures, or user feedback that might explain the churn?""",
            ),
            # Case: User has provided comprehensive initial context
            EvalCase(
                input="""I need to understand why our mobile app users are churning after the free trial.
                We've seen a 40% increase in trial-to-paid conversion drop over the last month.
                I want to focus on iOS users in the US market who signed up in the last 30 days.
                Our target is to get back to our previous 25% conversion rate.
                We recently changed our onboarding flow 6 weeks ago.""",
                expected="""Thanks for providing that context! I can see you're dealing with a significant drop in trial-to-paid conversion for iOS users. Let me gather a few more details to ensure our analysis is comprehensive:

## 1. User Behavior Patterns
* What specific actions or features correlate with users who do convert vs. those who don't?
* Are there particular points in the trial period where users typically drop off?

## 2. Onboarding Flow Impact
* What were the key changes in the new onboarding flow 6 weeks ago?
* Have you noticed any specific feedback or behavior changes since the update?

## 3. Competitive & Market Context
* Are there any external factors (competitor launches, market changes) that coincided with this drop?
* Have you seen similar patterns in Android or other markets that might provide clues?""",
            ),
        ],
        pytestconfig=pytestconfig,
    )
