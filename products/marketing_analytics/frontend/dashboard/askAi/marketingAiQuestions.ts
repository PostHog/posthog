import { MarketingDashboardView } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

/** Aimed at what a section cannot draw: another date range, a second dimension, or a reason rather
 * than a number. Nothing asks about cost, which a team reaches this dashboard long before connecting. */
export const MARKETING_AI_QUESTIONS: Record<MarketingDashboardView, string[]> = {
    [MarketingDashboardView.OVERVIEW]: [
        'Where is my growth actually coming from?',
        'Compare this quarter with the last one.',
        "What should I be looking at that this page doesn't show?",
    ],
    [MarketingDashboardView.ACQUISITION]: [
        'Which channels are growing, and which are quietly shrinking?',
        'Break new visitors down by campaign over the past 12 months.',
        'Is my traffic mix healthier than it was a year ago?',
    ],
    [MarketingDashboardView.ENGAGEMENT]: [
        'Do visitors from social read as much as visitors from search?',
        'Find the landing pages people leave fastest.',
        'Show me how engagement shifts across the week.',
    ],
    [MarketingDashboardView.RETENTION]: [
        'Show me monthly active users by month, over the past 12 months.',
        'Which channel sends people who are still here three months later?',
        'What do the people who stopped coming back have in common?',
    ],
    [MarketingDashboardView.CONVERSION]: [
        "What separates the people who convert from the people who don't?",
        'Track conversion rate week by week this year.',
        'Which landing page leads to the most conversions?',
    ],
}
