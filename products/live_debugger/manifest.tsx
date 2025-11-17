import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Live Debugger',
    scenes: {
        LiveDebugger: {
            name: 'Live Debugger',
            import: () => import('./frontend/LiveDebugger'),
            projectBased: true,
        },
    },
    routes: {
        '/live-debugger': ['LiveDebugger', 'liveDebugger'],
    },
    redirects: {},
    urls: {
        liveDebugger: (): string => '/live-debugger',
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
            category: 'Unreleased',
            type: 'live_debugger',
            href: urls.liveDebugger(),
            flag: FEATURE_FLAGS.LIVE_DEBUGGER,
            iconType: 'live_debugger',
            tags: ['alpha'],
            iconColor: ['var(--color-product-live-debugger-light)'] as FileSystemIconColor,
        },
    ],
}
