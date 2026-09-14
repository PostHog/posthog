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
                'Set up AI scanners that automatically analyze new session recordings as they come in. Each result emits a queryable event.',
            iconType: 'replay_vision',
            layout: 'app-container',
            docsHref: 'https://posthog.com/docs/replay-vision',
        },
        ReplayVisionScanner: {
            name: 'Replay vision scanner',
            import: () => import('./frontend/replay_scanners/ReplayScanner'),
            projectBased: true,
            iconType: 'replay_vision',
            layout: 'app-container',
        },
        ReplayVisionScannerEditor: {
            name: 'Replay vision scanner editor',
            import: () => import('./frontend/replay_scanners/ScannerEditorScene'),
            projectBased: true,
            iconType: 'replay_vision',
            layout: 'app-container',
        },
        ReplayVisionObservation: {
            name: 'Replay vision observation',
            import: () => import('./frontend/observations/ReplayObservation'),
            projectBased: true,
            iconType: 'replay_vision',
            layout: 'app-container',
        },
    },
    routes: {
        '/replay-vision': ['ReplayVision', 'replayVision'],
        '/replay-vision/observations/:observationId': ['ReplayVisionObservation', 'replayVisionObservation'],
        '/replay-vision/:id/template': ['ReplayVisionScannerEditor', 'replayVisionScannerTemplate'],
        '/replay-vision/:id/overview': ['ReplayVisionScannerEditor', 'replayVisionScannerOverview'],
        '/replay-vision/:id/details': ['ReplayVisionScannerEditor', 'replayVisionScannerDetails'],
        '/replay-vision/:id/configure': ['ReplayVisionScannerEditor', 'replayVisionScannerConfigure'],
        '/replay-vision/:id/triggers': ['ReplayVisionScannerEditor', 'replayVisionScannerTriggers'],
        '/replay-vision/:id/budget': ['ReplayVisionScannerEditor', 'replayVisionScannerBudget'],
        '/replay-vision/:id/self-driving': ['ReplayVisionScannerEditor', 'replayVisionScannerSelfDriving'],
        '/replay-vision/:id': ['ReplayVisionScanner', 'replayVision'],
    },
    redirects: {
        '/replay-vision/templates': '/replay-vision/new/template',
    },
    urls: {
        replayVision:
            /** @param id A UUID or 'new'. Omit for the scanner list page. */
            (id?: string): string => (id ? `/replay-vision/${id}` : '/replay-vision'),
        replayVisionTemplates: (): string => '/replay-vision/new/template',
        replayVisionScannerTemplate: (id: string): string => `/replay-vision/${id}/template`,
        replayVisionScannerOverview: (id: string): string => `/replay-vision/${id}/overview`,
        replayVisionScannerDetails: (id: string): string => `/replay-vision/${id}/details`,
        replayVisionScannerConfigure: (id: string): string => `/replay-vision/${id}/configure`,
        replayVisionScannerTriggers: (id: string): string => `/replay-vision/${id}/triggers`,
        replayVisionScannerBudget: (id: string): string => `/replay-vision/${id}/budget`,
        replayVisionScannerSelfDriving: (id: string): string => `/replay-vision/${id}/self-driving`,
        replayVisionObservation: (observationId: string): string => `/replay-vision/observations/${observationId}`,
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
            sceneKey: 'ReplayVision',
            sceneKeys: ['ReplayVision', 'ReplayVisionScanner'],
        },
    ],
}
