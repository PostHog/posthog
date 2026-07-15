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
                'Set up AI scanners that automatically analyze new session recordings as they come in. Each result emits a queryable event.',
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
        ReplayVisionAction: {
            name: 'Replay vision action',
            import: () => import('./frontend/replay_scanners/VisionActionScene'),
            projectBased: true,
            iconType: 'replay_vision',
            layout: 'app-container',
        },
        ReplayVisionActionEditor: {
            name: 'Replay vision action editor',
            import: () => import('./frontend/replay_scanners/ActionEditorScene'),
            projectBased: true,
            iconType: 'replay_vision',
            layout: 'app-container',
        },
        ReplayVisionActionRun: {
            name: 'Replay vision action run',
            import: () => import('./frontend/replay_scanners/VisionActionRunScene'),
            projectBased: true,
            iconType: 'replay_vision',
            layout: 'app-container',
        },
    },
    routes: {
        '/replay-vision': ['ReplayVision', 'replayVision'],
        '/replay-vision/observations/:observationId': ['ReplayVisionObservation', 'replayVisionObservation'],
        '/replay-vision/actions/:actionId/runs/:runId': ['ReplayVisionActionRun', 'replayVisionActionRun'],
        '/replay-vision/actions/:actionId/edit': ['ReplayVisionActionEditor', 'replayVisionActionEdit'],
        '/replay-vision/actions/:actionId': ['ReplayVisionAction', 'replayVisionAction'],
        '/replay-vision/:scannerId/actions/new': ['ReplayVisionActionEditor', 'replayVisionActionNew'],
        '/replay-vision/:id/template': ['ReplayVisionScannerEditor', 'replayVisionScannerTemplate'],
        '/replay-vision/:id/configure': ['ReplayVisionScannerEditor', 'replayVisionScannerConfigure'],
        '/replay-vision/:id/triggers': ['ReplayVisionScannerEditor', 'replayVisionScannerTriggers'],
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
        replayVisionScannerConfigure: (id: string): string => `/replay-vision/${id}/configure`,
        replayVisionScannerTriggers: (id: string): string => `/replay-vision/${id}/triggers`,
        replayVisionScannerSelfDriving: (id: string): string => `/replay-vision/${id}/self-driving`,
        replayVisionObservation: (observationId: string): string => `/replay-vision/observations/${observationId}`,
        replayVisionAction: (actionId: string): string => `/replay-vision/actions/${actionId}`,
        replayVisionActionRun: (actionId: string, runId: string): string =>
            `/replay-vision/actions/${actionId}/runs/${runId}`,
        replayVisionActionNew: (scannerId: string): string => `/replay-vision/${scannerId}/actions/new`,
        replayVisionActionEdit: (actionId: string): string => `/replay-vision/actions/${actionId}/edit`,
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
            pinnedByDefault: true,
            sceneKey: 'ReplayVision',
            sceneKeys: ['ReplayVision', 'ReplayVisionScanner'],
        },
    ],
}
