import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

export interface PARecurringReport {
    key: string
    headline: string
    lead: string
    frequency: 'daily' | 'weekly'
    title: string
    /**
     * Handed to the AI-subscription planner, which writes and runs its own HogQL. Names the
     * event properties explicitly so it queries the right ones rather than guessing.
     */
    prompt: string
}

// All weekly: daily windows make week-over-week comparisons and retention math meaningless for
// most projects, and a weekly digest is the cadence these questions are worth thinking about.
export const PA_RECURRING_REPORTS: PARecurringReport[] = [
    {
        key: 'usage-digest',
        headline: 'How your product was used',
        lead: 'Active users, top pages and top events for the week, with what moved.',
        frequency: 'weekly',
        title: 'Weekly product usage digest',
        prompt: [
            'Summarize product usage for the last 7 days using this project’s events.',
            'Report weekly active users (unique persons), total events, and $pageview volume,',
            'each compared with the previous 7 days.',
            'List the top 10 pages by $pageview count using the $pathname property,',
            'and the top custom events (exclude event names starting with $).',
            'Call out anything that moved more than 20% week over week,',
            'and finish with the single most notable change and a plausible reason for it.',
        ].join(' '),
    },
    {
        key: 'growing-declining',
        headline: 'What is growing and what is declining',
        lead: 'The fastest-rising and fastest-falling events week over week.',
        frequency: 'weekly',
        title: 'Growing and declining events',
        prompt: [
            'Compare event volume for the last 7 days against the previous 7 days for every event',
            'name in this project, excluding internal events that start with $ (but keep $pageview).',
            'Rank the five fastest-growing and five fastest-declining events by relative change,',
            'ignoring events with fewer than 100 occurrences in both windows.',
            'For each, give the counts and whether unique users moved the same way as event volume,',
            'since volume rising on flat users means heavier use rather than more reach.',
            'Close with one hypothesis worth checking for the biggest decline.',
        ].join(' '),
    },
    {
        key: 'activation-retention',
        headline: 'Are new users coming back',
        lead: 'This week’s new users, how many returned, and where they landed first.',
        frequency: 'weekly',
        title: 'New-user activation and retention',
        prompt: [
            'Report on new-user activation using $pageview events.',
            'Count persons whose first event ever was in the last 7 days, the share of them that',
            'returned on a later day within the same week, and compare with the previous week’s cohort.',
            'List the top three first-touch pages for new users using $entry_current_url when set,',
            'otherwise the $pathname of their first $pageview, and note whether the landing page',
            'correlates with returning. End with the one thing most likely to improve week-one retention.',
        ].join(' '),
    },
]

/**
 * Opens the AI-subscription form with the report already written, so setting one up is choosing a
 * destination and a cadence rather than composing a prompt.
 */
export function urlForRecurringReport(report: PARecurringReport): string {
    return combineUrl(urls.subscriptionNew(), {
        resource_type: 'ai_prompt',
        prompt: report.prompt,
        title: report.title,
        frequency: report.frequency,
        target_type: 'slack',
    }).url
}
