// Shared by the scene's "New topic" button and the empty state's primary action,
// so both open PostHog AI armed the same way.
export const NEW_TOPIC_PROMPT = `!I want to set up a new user research topic. Help me work through:
1. What I want to learn — the feature, behavior, or question to research.
2. Who to interview — let me give you emails or distinct IDs, or help me pick from a cohort.
3. The interview questions — 3-6 open-ended, conversational prompts in a sensible order.
Then create the topic using the create_user_interview_topic tool. Don't try to send emails or generate links yourself — once the topic exists I'll do that from the topic page.`

export const NEW_TOPIC_SUGGESTIONS = [
    'Interview recent signups about their onboarding experience',
    'Talk to power users about what they wish the product did better',
    'Interview customers who churned in the last 30 days',
    'Research how teams are using dashboards day-to-day',
]
