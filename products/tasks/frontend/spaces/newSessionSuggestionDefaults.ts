import type { ComposerPrefillRequest } from 'products/posthog_ai/frontend/api/runner'

export type NewSessionSuggestionIcon = 'trends' | 'bug' | 'canvas' | 'code' | 'revenue' | 'feedback'

export interface NewSessionSuggestion {
    id: string
    label: string
    description: string
    prompt: string
    icon: NewSessionSuggestionIcon
    mode?: ComposerPrefillRequest['mode']
}

export const DEFAULT_NEW_SESSION_SUGGESTIONS: NewSessionSuggestion[] = [
    {
        id: 'feature-analysis',
        label: 'Run a feature analysis',
        description: 'Adoption, engagement, and retention',
        icon: 'trends',
        mode: 'auto',
        prompt: "Analyze how a feature is performing: adoption, engagement, and retention of users who use it compared with users who don't. Build a canvas that explains what you found, with the charts behind it.\n\n\nUser input:\n- Feature to analyze:\n- Time period (optional):",
    },
    {
        id: 'debug-user-issue',
        label: 'Debug a user issue',
        description: "Trace a user's events, replays, and errors",
        icon: 'bug',
        mode: 'auto',
        prompt: 'Help me debug an issue a specific user is hitting. Pull their recent events, session replays, and errors, then figure out what went wrong. Build a canvas that explains what you found and the evidence behind it.\n\n\nUser input:\n- Describe the user issue:\n- User identifier (distinct ID, email address, etc):',
    },
    {
        id: 'build-canvas',
        label: 'Build a canvas',
        description: 'Research and explain a question',
        icon: 'canvas',
        mode: 'auto',
        prompt: 'Research a question about our product, then build a canvas that explains the answer. Include the charts that show it and short written context for what they mean.\n\n\nUser input:\n- What should the canvas explain:\n- Time period (optional):',
    },
    {
        id: 'build-feature',
        label: 'Build a new feature',
        description: 'Design and implement something new',
        icon: 'code',
        mode: 'plan',
        prompt: 'Help me build a new feature. Propose an approach, then implement it. Open a PR if appropriate.\n\n\nUser input:\n- Describe the feature you want:\n- Any constraints or requirements (optional):',
    },
    {
        id: 'revenue-patterns',
        label: 'Understand revenue patterns',
        description: 'Trends over time, by plan, and by cohort',
        icon: 'revenue',
        mode: 'auto',
        prompt: 'Analyze our revenue trends. Break them down over time, by plan, and by cohort, and call out notable changes and likely drivers. Build a canvas that explains what you found, with the charts behind it.\n\n\nUser input:\n- What revenue question are you trying to answer:\n- Time period (optional):',
    },
    {
        id: 'summarize-feedback',
        label: 'Summarize user & agent feedback',
        description: 'Common themes across recent feedback',
        icon: 'feedback',
        mode: 'auto',
        prompt: 'Summarize recent user and support agent feedback. Surface the common themes, complaints, and requests. Build a canvas that explains the themes, with examples behind each one.\n\n\nUser input:\n- Feedback source or topic to focus on:\n- Time period (optional):',
    },
]
