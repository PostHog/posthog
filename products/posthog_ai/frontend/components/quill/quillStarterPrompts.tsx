import type { FileSystemIconType } from '~/queries/schema/schema-general'

import type { PermissionMode } from '../../utils/composerModes'

export interface QuillStarterPrompt {
    label: string
    description: string
    prompt: string
    /** The product icon type, so the card uses the same icon and colour as the product elsewhere. */
    iconType: FileSystemIconType
    mode?: PermissionMode
}

export const QUILL_STARTER_PROMPTS: readonly QuillStarterPrompt[] = [
    {
        label: 'Debug a user issue',
        description: "Trace a specific user's events, replays, and errors",
        iconType: 'error_tracking',
        mode: 'auto',
        prompt: 'Help me debug an issue a specific user is hitting. Pull their recent events, session replays, and errors, then figure out what went wrong.\n\n\nUser input:\n- Describe the user issue:\n- User identifier (distinct ID, email address, etc):',
    },
    {
        label: 'Run a feature analysis',
        description: 'Adoption, engagement, and retention of a feature',
        iconType: 'product_analytics',
        mode: 'auto',
        prompt: "Analyze how a feature is performing: adoption, engagement, and retention of users who use it vs. those who don't.\n\n\nUser input:\n- Feature to analyze:\n- Time period (optional):",
    },
    {
        label: 'Understand revenue patterns',
        description: 'Trends over time, by plan, and by cohort',
        iconType: 'revenue_analytics',
        mode: 'auto',
        prompt: 'Analyze our revenue trends. Break it down over time, by plan, and by cohort, and call out notable changes and likely drivers.\n\n\nUser input:\n- What revenue question are you trying to answer:\n- Time period (optional):',
    },
    {
        label: 'Summarize user feedback',
        description: 'Common themes across recent feedback',
        iconType: 'survey',
        mode: 'auto',
        prompt: 'Summarize recent user and support feedback. Surface the common themes, complaints, and requests, with examples behind each one.\n\n\nUser input:\n- Feedback source or topic to focus on:\n- Time period (optional):',
    },
    {
        label: 'Interpret experiment results',
        description: 'Significance and what to do next',
        iconType: 'experiment',
        mode: 'auto',
        prompt: "Interpret the results of an experiment. Explain what the metrics show, whether it's significant, and what to do next.\n\n\nUser input:\n- Experiment name or key:\n- What decision are you trying to make (optional):",
    },
    {
        label: 'Build something',
        description: 'Design and ship a feature or a fix',
        iconType: 'task',
        mode: 'plan',
        prompt: 'Help me build something. Propose an approach, then implement it. Open a PR if appropriate.\n\n\nUser input:\n- Describe what you want to build or fix:\n- Any constraints or requirements (optional):',
    },
]
