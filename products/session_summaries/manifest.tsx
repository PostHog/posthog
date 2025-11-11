import { urls } from 'scenes/urls'

import { FileSystemIconColor, FileSystemIconType, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Session summaries',
    scenes: {
        SessionGroupSummariesTable: {
            name: 'Session summaries',
            import: () => import('./frontend/SessionGroupSummariesTable'),
            projectBased: true,
            description: 'View and analyze session summaries.',
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
    fileSystemTypes: {
        session_summaries: {
            name: 'Session summary',
            iconType: 'insight/hog' as FileSystemIconType,
            href: () => urls.sessionSummaries(),
            iconColor: [
                'var(--color-product-session-replay-light)',
                'var(--color-product-session-replay-dark)',
            ] as FileSystemIconColor,
            filterKey: 'session_summaries',
        },
    },
    treeItemsProducts: [
        {
            path: 'Session summaries',
            category: 'Behavior',
            href: urls.sessionSummaries(),
            type: 'session_summaries',
            iconType: 'insight/hog',
            iconColor: [
                'var(--color-product-session-replay-light)',
                'var(--color-product-session-replay-dark)',
            ] as FileSystemIconColor,
            sceneKey: 'SessionSummaries',
        },
    ],
}
