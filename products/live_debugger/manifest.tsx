import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Live Debugger',
    scenes: {
        LiveDebugger: {
            name: 'Live Debugger',
            import: () => import('./frontend/LiveDebugger'),
            projectBased: true,
        },
        DebuggingSessions: {
            name: 'Debugging Sessions',
            import: () => import('./frontend/DebuggingSessions'),
            projectBased: true,
        },
        DebuggingSession: {
            name: 'Debugging Session',
            import: () => import('./frontend/DebuggingSession'),
            projectBased: true,
        },
    },
    routes: {
        '/live-debugger': ['LiveDebugger', 'liveDebugger'],
        '/live-debugger/sessions': ['DebuggingSessions', 'debuggingSessions'],
        '/live-debugger/sessions/:id': ['DebuggingSession', 'debuggingSession'],
    },
    redirects: {},
    urls: {
        liveDebugger: (): string => '/live-debugger',
        debuggingSessions: (): string => '/live-debugger/sessions',
        debuggingSession: (id: string): string => `/live-debugger/sessions/${id}`,
    },
    fileSystemTypes: {
        live_debugger: {
            name: 'Live Debugger',
            iconType: 'live_debugger',
            href: () => urls.liveDebugger(),
            iconColor: ['var(--color-product-live-debugger-light)'],
            filterKey: 'live_debugger',
            flag: FEATURE_FLAGS.LIVE_DEBUGGER,
        },
    },
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Live Debugger',
            intents: [ProductKey.LIVE_DEBUGGER],
            category: ProductItemCategory.UNRELEASED,
            type: 'live_debugger',
            href: urls.liveDebugger(),
            flag: FEATURE_FLAGS.LIVE_DEBUGGER,
            iconType: 'live_debugger',
            tags: ['alpha'],
            iconColor: ['var(--color-product-live-debugger-light)'] as FileSystemIconColor,
        },
    ],
}
