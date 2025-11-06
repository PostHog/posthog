import pytest

from braintrust import EvalCase

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from products.enterprise.backend.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from products.enterprise.backend.hogai.graph.graph import AssistantGraph
from products.enterprise.backend.hogai.utils.types import AssistantNodeName, AssistantState
from products.enterprise.backend.models.assistant import Conversation

from ..base import MaxPublicEval
from ..scorers import ToolRelevance


@pytest.fixture
def call_root(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(router=lambda state: AssistantNodeName.END)
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(messages):
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=messages)] if isinstance(messages, str) else messages
        )
        raw_state = await graph.ainvoke(initial_state, {"configurable": {"thread_id": conversation.id}})
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.mark.django_db
async def eval_root_documentation(call_root, pytestconfig):
    await MaxPublicEval(
        experiment_name="root_documentation",
        task=call_root,
        scores=[ToolRelevance(semantic_similarity_args={"query"})],
        data=[
            # Documentation search when the user asks about SDK integration or instrumentation
            EvalCase(
                input="import posthog from 'posthog-js' posthog.captureException(error) in my react app i manually capture exceptions but i don't see them on the dashboard",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "posthog-js captureException not showing exceptions on dashboard"},
                    id="call_oejkj9HpAcIVAqTjxaXaofyA",
                ),
            ),
            # Basic PostHog product questions
            EvalCase(
                input="How do I set up event tracking in PostHog?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "set up event tracking"},
                    id="call_doc_search_1",
                ),
            ),
            EvalCase(
                input="What is a cohort in PostHog and how do I create one?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "cohort creation"},
                    id="call_doc_search_2",
                ),
            ),
            EvalCase(
                input="How does PostHog's session recording work?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "session recording"},
                    id="call_doc_search_3",
                ),
            ),
            EvalCase(
                input="Can you explain PostHog's feature flags functionality?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "feature flags functionality"},
                    id="call_doc_search_4",
                ),
            ),
            # SDK and integration questions
            EvalCase(
                input="How do I install the PostHog SDK for Python?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "install PostHog SDK for Python"},
                    id="call_doc_search_5",
                ),
            ),
            EvalCase(
                input="posthog js sdk not working in my next.js app",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "posthog js sdk next.js troubleshooting"},
                    id="call_doc_search_6",
                ),
            ),
            EvalCase(
                input="How to track custom events with posthog react library",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "track custom events posthog react"},
                    id="call_doc_search_7",
                ),
            ),
            EvalCase(
                input="posthog.capture() vs posthog.track() whats the difference",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "difference between capture and track"},
                    id="call_doc_search_8",
                ),
            ),
            # Feature-specific questions
            EvalCase(
                input="How do I create a funnel analysis in PostHog?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "create funnel analysis"},
                    id="call_doc_search_9",
                ),
            ),
            EvalCase(
                input="What's the difference between trends and insights in PostHog?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "difference between trends and insights"},
                    id="call_doc_search_10",
                ),
            ),
            EvalCase(
                input="How do I set up A/B testing with PostHog feature flags?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "A/B testing with feature flags"},
                    id="call_doc_search_11",
                ),
            ),
            EvalCase(
                input="posthog dashboard widgets how to customize them",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "customize dashboard widgets"},
                    id="call_doc_search_12",
                ),
            ),
            # Terse/messy user input
            EvalCase(
                input="ph not tracking events???",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "events not tracking troubleshooting"},
                    id="call_doc_search_13",
                ),
            ),
            EvalCase(
                input="help feature flag setup",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "feature flag setup"},
                    id="call_doc_search_14",
                ),
            ),
            EvalCase(
                input="sdk integration issues react native",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "react native SDK integration troubleshooting"},
                    id="call_doc_search_16",
                ),
            ),
            EvalCase(
                input="cant see recordings",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "session recordings not visible troubleshooting"},
                    id="call_doc_search_17",
                ),
            ),
            # Troubleshooting and debugging
            EvalCase(
                input="My PostHog events aren't showing up in the dashboard, what could be wrong?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "events not showing up in dashboard troubleshooting"},
                    id="call_doc_search_18",
                ),
            ),
            EvalCase(
                input="Session recordings are blank, how do I fix this?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "blank session recordings fix"},
                    id="call_doc_search_19",
                ),
            ),
            EvalCase(
                input="PostHog feature flags not working in production environment",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "feature flags not working in production"},
                    id="call_doc_search_20",
                ),
            ),
            EvalCase(
                input="Why are my PostHog cohorts not updating automatically?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "cohorts not updating automatically"},
                    id="call_doc_search_21",
                ),
            ),
            # Configuration and setup questions
            EvalCase(
                input="How do I configure PostHog for GDPR compliance?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "GDPR compliance configuration"},
                    id="call_doc_search_22",
                ),
            ),
            EvalCase(
                input="What are the different PostHog deployment options?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "deployment options"},
                    id="call_doc_search_23",
                ),
            ),
            EvalCase(
                input="posthog self hosted vs cloud which one should i choose",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "self hosted vs cloud comparison"},
                    id="call_doc_search_24",
                ),
            ),
            # API and integration questions
            EvalCase(
                input="How do I use PostHog's REST API to query events?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "REST API query events"},
                    id="call_doc_search_25",
                ),
            ),
            EvalCase(
                input="PostHog webhook integration with Slack how to set up",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "webhook Slack integration setup"},
                    id="call_doc_search_26",
                ),
            ),
            EvalCase(
                input="can posthog integrate with segment?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "segment integration"},
                    id="call_doc_search_27",
                ),
            ),
            # Performance and limits
            EvalCase(
                input="What are PostHog's rate limits for event ingestion?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "rate limits event ingestion"},
                    id="call_doc_search_28",
                ),
            ),
            EvalCase(
                input="my posthog is slow how to optimize performance",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "optimize performance"},
                    id="call_doc_search_29",
                ),
            ),
            # Mobile and platform-specific
            EvalCase(
                input="PostHog iOS SDK setup guide",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "iOS SDK setup"},
                    id="call_doc_search_30",
                ),
            ),
            EvalCase(
                input="android posthog tracking not working",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "android tracking not working troubleshooting"},
                    id="call_doc_search_31",
                ),
            ),
            EvalCase(
                input="flutter posthog plugin how to use",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "flutter plugin usage"},
                    id="call_doc_search_32",
                ),
            ),
            # Ensure calls docs, not insights
            EvalCase(
                input="Can I see which browser or device type a user is using from the default event properties?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "default event properties browser device type"},
                    id="call_doc_search_34",
                ),
            ),
            EvalCase(
                input="What geographic information does PostHog automatically capture about my users?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "automatic geographic information capture"},
                    id="call_doc_search_35",
                ),
            ),
            EvalCase(
                input="How do I delete events from PostHog?",
                expected=AssistantToolCall(
                    name="search",
                    args={"kind": "docs", "query": "delete events from PostHog"},
                    id="call_doc_search_36",
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )
