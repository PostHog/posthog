import {
    IconBox,
    IconBug,
    IconChat,
    IconLineGraph,
    IconListCheck,
    IconPencil,
    IconPullRequest,
    IconSupport,
    IconTestTube,
    IconTrends,
    IconWarning,
} from '@posthog/icons'

export type SpaceLoopTemplateCategory = 'engineering' | 'operations'

export const SPACE_LOOP_TEMPLATE_CATEGORIES: { value: SpaceLoopTemplateCategory; label: string }[] = [
    { value: 'engineering', label: 'Engineering' },
    { value: 'operations', label: 'Operations' },
]

export type SpaceLoopTemplateTone = 'info' | 'destructive' | 'completed' | 'success' | 'warning'

export interface SpaceLoopTemplate {
    id: string
    category: SpaceLoopTemplateCategory
    Icon: typeof IconBug
    tone: SpaceLoopTemplateTone
    name: string
    description: string
    /** How the loop starts, shown on the card. A label that starts with "Triggered" gets the event icon. */
    triggerLabel: string
    worksWith: string[]
    /** What the loop does on each run. The builder session starts from it. */
    instructions: string
}

// The same templates as PostHog Desktop's Loops page (`loopTemplates.ts`), so both apps offer the same starting points.
export const SPACE_LOOP_TEMPLATES: SpaceLoopTemplate[] = [
    {
        id: 'pr-review-digest',
        category: 'engineering',
        Icon: IconPullRequest,
        tone: 'info',
        name: 'PR review digest',
        description: 'Summarize open pull requests, their review and CI status, and what needs attention.',
        triggerLabel: 'Runs weekdays at 11:00',
        worksWith: ['GitHub', 'Slack'],
        instructions:
            'Summarize the open pull requests in this repository. For each, note its review status, CI status, and how long it has been waiting. Call out anything that needs attention, then post the summary to the team.',
    },
    {
        id: 'ci-failure-summary',
        category: 'engineering',
        Icon: IconBug,
        tone: 'destructive',
        name: 'CI failure summary',
        description: 'Digest the failing CI runs from the last day and post a summary to your team channel.',
        triggerLabel: 'Runs daily at 9:00',
        worksWith: ['GitHub', 'Slack'],
        instructions:
            'Review the CI runs from the last 24 hours. Summarize which jobs failed, the likely cause of each, and any patterns across runs. Post the summary to the team channel.',
    },
    {
        id: 'flaky-test-tracker',
        category: 'engineering',
        Icon: IconTestTube,
        tone: 'completed',
        name: 'Flaky test tracker',
        description: 'Find tests that pass and fail intermittently across recent CI runs, and open an issue.',
        triggerLabel: 'Runs Mondays at 9:00',
        worksWith: ['GitHub'],
        instructions:
            'Look through recent CI runs and identify tests that pass and fail intermittently on unchanged code. List the flakiest tests with links to failing runs, and open an issue tracking them.',
    },
    {
        id: 'dependency-update-check',
        category: 'engineering',
        Icon: IconBox,
        tone: 'success',
        name: 'Dependency update check',
        description: 'Scan for outdated packages, security patches, and breaking changes, then open a PR.',
        triggerLabel: 'Runs Mondays at 11:30',
        worksWith: ['GitHub'],
        instructions:
            "Check this repository's dependencies for outdated versions, security advisories, and breaking changes. Open a pull request that bumps the safe updates and summarize anything that needs manual review.",
    },
    {
        id: 'release-notes-drafter',
        category: 'engineering',
        Icon: IconPencil,
        tone: 'warning',
        name: 'Release notes drafter',
        description: 'Draft user-facing release notes each time a pull request merges to the main branch.',
        triggerLabel: 'Triggered when a PR merges',
        worksWith: ['GitHub'],
        instructions:
            'When a pull request merges to the main branch, draft a user-facing release note for the change: what changed, why it matters, and any migration steps. Keep the tone plain and concrete.',
    },
    {
        id: 'issue-triage',
        category: 'engineering',
        Icon: IconListCheck,
        tone: 'success',
        name: 'Issue triage',
        description: 'Review new issues, categorize bugs and feature requests, and flag likely duplicates.',
        triggerLabel: 'Triggered by new issues',
        worksWith: ['GitHub'],
        instructions:
            'When a new issue is opened, categorize it (bug, feature request, question, or docs), assess its severity, and check whether it duplicates an existing issue. Apply the right labels and comment with your reasoning.',
    },
    {
        id: 'standup-summary',
        category: 'operations',
        Icon: IconChat,
        tone: 'warning',
        name: 'Standup summary',
        description: "Post a morning summary of what the team shipped yesterday and what's in progress.",
        triggerLabel: 'Runs weekdays at 9:00',
        worksWith: ['GitHub', 'Slack'],
        instructions:
            'Summarize what the team shipped yesterday (merged PRs, closed issues) and what is currently in progress. Keep it short and skimmable, then post it to the standup channel.',
    },
    {
        id: 'weekly-review',
        category: 'operations',
        Icon: IconLineGraph,
        tone: 'info',
        name: 'Weekly review',
        description: "A Friday summary of the week's shipped work and what's carrying into next week.",
        triggerLabel: 'Runs Fridays at 16:00',
        worksWith: ['GitHub', 'Slack'],
        instructions:
            'Write a review of the week: the PRs merged, issues closed, and notable changes, plus what is still open and carrying into next week. Post it to the team channel.',
    },
    {
        id: 'support-ticket-triage',
        category: 'operations',
        Icon: IconSupport,
        tone: 'success',
        name: 'Support ticket triage',
        description: 'Triage new support tickets: categorize, set priority, and draft a reply for approval.',
        triggerLabel: 'Runs every hour',
        worksWith: ['Linear', 'Slack'],
        instructions:
            "Review support tickets opened since the last run. Categorize each, set a priority, link any related issue, and draft a reply for a human to approve before it's sent.",
    },
    {
        id: 'incident-digest',
        category: 'operations',
        Icon: IconWarning,
        tone: 'destructive',
        name: 'Incident digest',
        description: 'Summarize open incidents and alerts and their current status each morning.',
        triggerLabel: 'Runs daily at 8:00',
        worksWith: ['Sentry', 'Slack'],
        instructions:
            'Summarize the open incidents and active alerts, their severity, and current status. Flag anything that has been open too long, then post the digest to the on-call channel.',
    },
    {
        id: 'metrics-digest',
        category: 'operations',
        Icon: IconTrends,
        tone: 'completed',
        name: 'Metrics digest',
        description: 'Summarize key product metrics week over week and flag notable changes.',
        triggerLabel: 'Runs Mondays at 9:00',
        worksWith: ['PostHog', 'Slack'],
        instructions:
            'Pull the key product metrics for the last week, compare them to the prior week, and call out anything that moved notably. Post a short digest to the team channel.',
    },
    {
        id: 'changelog-drafter',
        category: 'operations',
        Icon: IconPencil,
        tone: 'success',
        name: 'Changelog drafter',
        description: 'Draft a weekly customer-facing changelog from the changes that shipped.',
        triggerLabel: 'Runs Fridays at 15:00',
        worksWith: ['GitHub'],
        instructions:
            'From the pull requests merged this week, draft a customer-facing changelog: group related changes, write plain-language entries, and leave anything internal out. Save it as a draft for review.',
    },
]

/** What a template puts in the loop builder box: the loop's job, then when it runs. */
export function spaceLoopTemplateDraft(template: SpaceLoopTemplate): string {
    return `${template.name}: ${template.instructions} ${template.triggerLabel}.`
}
