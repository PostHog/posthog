import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'ReplayVision',
    scenes: {
        ReplayLenses: {
            name: 'Replay vision',
            import: () => import('./frontend/replay_lenses/ReplayLensesScene'),
            projectBased: true,
            description:
                'Configure named lenses that PostHog applies to completed session recordings. Results land as queryable events.',
            iconType: 'replay_vision',
            layout: 'app-container',
        },
        ReplayLens: {
            name: 'Lens',
            import: () => import('./frontend/replay_lenses/ReplayLens'),
            projectBased: true,
            iconType: 'replay_vision',
            layout: 'app-container',
        },
    },
    routes: {
        '/replay-lenses': ['ReplayLenses', 'replayLenses'],
        '/replay-lenses/:id': ['ReplayLens', 'replayLens'],
    },
    redirects: {},
    urls: {
        replayLenses: (): string => '/replay-lenses',
        replayLens:
            /** @param id A UUID or 'new'. */
            (id: string): string => `/replay-lenses/${id}`,
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
            href: urls.replayLenses(),
            tags: ['alpha'],
            flag: FEATURE_FLAGS.REPLAY_VISION,
            sceneKey: 'ReplayLenses',
        },
    ],
}
