import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Session summaries',
    scenes: {
        SessionGroupSummariesTable: {
            name: 'Session summaries',
            import: () => import('./frontend/SessionGroupSummariesTable'),
            projectBased: true,
            description:
                'View and deep-dive into AI-generated summaries of session recordings. Create summaries from the Session replay page by applying filters and asking PostHog AI to summarize sessions. If no filters, ask PostHog AI to find and summarize sessions based on provided criteria.',
            iconType: 'insight/hog',
        },
        SessionGroupSummary: {
            name: 'Session summary',
            import: () => import('./frontend/SessionGroupSummaryScene'),
            projectBased: true,
            description: 'View detailed session group summary.',
            iconType: 'insight/hog',
        },
    },
    routes: {
        '/session-summaries': ['SessionGroupSummariesTable', 'sessionGroupSummariesTable'],
        '/session-summaries/:sessionGroupId': ['SessionGroupSummary', 'sessionGroupSummary'],
    },
    urls: {
        sessionSummaries: (): string => '/session-summaries',
        sessionSummary: (sessionGroupId: string): string => `/session-summaries/${sessionGroupId}`,
    },
}
