import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'ReplayVision',
    scenes: {
        ReplayVision: {
            name: 'Replay vision',
            import: () => import('./frontend/replay_scanners/ReplayScannersScene'),
            projectBased: true,
            description:
                'Configure named scanners that PostHog applies to completed session recordings. Results land as queryable events.',
            iconType: 'replay_vision',
            layout: 'app-container',
        },
        ReplayVisionScanner: {
            name: 'Replay vision scanner',
            import: () => import('./frontend/replay_scanners/ReplayScanner'),
            projectBased: true,
            iconType: 'replay_vision',
            layout: 'app-container',
        },
    },
    routes: {
        '/replay-vision': ['ReplayVision', 'replayVision'],
        '/replay-vision/:id': ['ReplayVisionScanner', 'replayVision'],
    },
    redirects: {},
    urls: {
        replayVision:
            /** @param id A UUID or 'new'. Omit for the scanner list page. */
            (id?: string): string => (id ? `/replay-vision/${id}` : '/replay-vision'),
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Replay vision',
            category: ProductItemCategory.BEHAVIOR,
            intents: [ProductKey.REPLAY_VISION],
            type: 'replay_vision',
            iconType: 'replay_vision' as FileSystemIconType,
            iconColor: [
                'var(--color-product-session-replay-light)',
                'var(--color-product-session-replay-dark)',
            ] as FileSystemIconColor,
            href: urls.replayVision(),
            tags: ['beta'],
            flag: FEATURE_FLAGS.REPLAY_VISION,
            sceneKey: 'ReplayVision',
            sceneKeys: ['ReplayVision', 'ReplayVisionScanner'],
        },
    ],
}
