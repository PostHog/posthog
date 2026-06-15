import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { replayScannerSceneLogicType } from './replayScannerSceneLogicType'

export const replayScannerSceneLogic = kea<replayScannerSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannerSceneLogic']),

    actions({
        setScannerId: (scannerId: string) => ({ scannerId }),
    }),

    reducers({
        scannerId: [
            'new' as string,
            {
                setScannerId: (_, { scannerId }) => scannerId,
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.scannerId],
            (scannerId: string): Breadcrumb[] => [
                {
                    key: 'replay-vision',
                    name: 'Replay vision',
                    path: urls.replayVision(),
                    iconType: 'replay_vision',
                },
                {
                    key: scannerId === 'new' ? 'new-scanner' : `scanner-${scannerId}`,
                    name: scannerId === 'new' ? 'New scanner' : 'Scanner',
                    path: urls.replayVision(scannerId),
                },
            ],
        ],
    }),

    urlToAction(({ actions, values }) => ({
        [urls.replayVision(':id')]: ({ id }) => {
            const scannerId = id || 'new'
            if (scannerId !== values.scannerId) {
                actions.setScannerId(scannerId)
            }
        },
    })),
])
