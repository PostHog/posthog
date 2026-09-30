import { MarketingDashboardView } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

export const MARKETING_AI_QUESTIONS: Record<MarketingDashboardView, string[]> = {
    [MarketingDashboardView.OVERVIEW]: [
        'Which channels contributed most to growth?',
        'Compare this quarter with the previous quarter.',
        'What changed most in this date range?',
    ],
    [MarketingDashboardView.ACQUISITION]: [
        'Which channels are growing or declining?',
        'Show new visitors by campaign for the past 12 months.',
        'Compare the traffic mix with last year.',
    ],
    [MarketingDashboardView.ENGAGEMENT]: [
        'Compare engagement from social and search.',
        'Which landing pages have the highest bounce rate?',
        'How does engagement change by day of week?',
    ],
    [MarketingDashboardView.RETENTION]: [
        'Show monthly active users for the past 12 months.',
        'Which channels have the highest three-month retention?',
        'What do visitors who did not return have in common?',
    ],
    [MarketingDashboardView.CONVERSION]: [
        'Compare visitors who converted with visitors who did not.',
        'Show the conversion rate by week for this year.',
        'Which landing pages lead to the most conversions?',
    ],
}
