import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Toolbar',
    scenes: {
        Toolbar: {
            name: 'Toolbar',
            projectBased: true,
            description: 'PostHog toolbar launches PostHog right in your app or website.',
            iconType: 'toolbar',
        },
    },
    urls: {
        toolbarLaunch: (): string => '/toolbar',
    },
    treeItemsProducts: [
        {
            path: 'Toolbar',
            intents: [ProductKey.TOOLBAR],
            href: urls.toolbarLaunch(),
            type: 'toolbar',
            category: 'Tools',
            iconType: 'toolbar',
            sceneKey: 'Toolbar',
        },
    ],
}
