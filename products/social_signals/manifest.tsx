import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { ProductItemCategory } from '../../frontend/src/queries/schema/schema-general'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'SocialSignals',
    scenes: {
        SocialSignals: {
            name: 'Social signals',
            projectBased: true,
            import: () => import('./frontend/scenes/SocialSignalsScene'),
            iconType: 'social_signals',
        },
        SocialSignalsSettings: {
            name: 'Social signals settings',
            projectBased: true,
            import: () => import('./frontend/scenes/SocialSignalsSettingsScene'),
            iconType: 'social_signals',
        },
    },
    routes: {
        '/social_signals': ['SocialSignals', 'socialSignals'],
        '/social_signals/settings': ['SocialSignalsSettings', 'socialSignalsSettings'],
    },
    redirects: {},
    urls: {
        socialSignals: (): string => '/social_signals',
        socialSignalsSettings: (): string => '/social_signals/settings',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Social signals',
            intents: [ProductKey.SOCIAL_SIGNALS],
            category: ProductItemCategory.UNRELEASED,
            href: urls.socialSignals(),
            iconType: 'social_signals' as FileSystemIconType,
            tags: ['alpha'],
            sceneKey: 'SocialSignals',
        },
    ],
}
