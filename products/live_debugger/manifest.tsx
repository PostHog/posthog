import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Live Debugger',
    scenes: {
        LiveDebugger: {
            name: 'Live debugger',
            import: () => import('./frontend/LiveDebugger'),
            projectBased: true,
            description: 'Set breakpoints in your running code and inspect the state captured when they hit.',
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
            displayLabel: 'Live debugger',
            intents: [ProductKey.LIVE_DEBUGGER],
            sceneKey: 'LiveDebugger',
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
