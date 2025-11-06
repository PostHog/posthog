import { urls } from 'scenes/urls'

import { FileSystemIconColor, FileSystemIconType, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Session summaries',
    scenes: {
        SessionSummaries: {
            name: 'Session summaries',
            import: () => import('./frontend/SessionSummariesScene'),
            projectBased: true,
            description: 'View and analyze session summaries.',
            iconType: 'insight/hog',
        },
    },
    routes: {
        '/session-summaries': ['SessionSummaries', 'sessionSummaries'],
    },
    urls: {
        sessionSummaries: (): string => '/session-summaries',
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
