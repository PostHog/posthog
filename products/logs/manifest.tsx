import { FEATURE_FLAGS } from 'lib/constants'
import { PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Logs',
    scenes: {
        Logs: {
            import: () => import('./frontend/LogsScene'),
            projectBased: true,
            name: 'Logs',
            activityScope: 'Logs',
            layout: 'app-container',
        },
    },
    routes: {
        '/logs': ['Logs', 'logs'],
    },
    redirects: {},
    urls: { logs: (): string => '/logs' },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Logs',
            iconType: 'live',
            href: urls.logs(),
            flag: FEATURE_FLAGS.LOGS,
            visualOrder: PRODUCT_VISUAL_ORDER.logs,
        },
    ],
}
