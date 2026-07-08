import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { replayObservationSceneLogicType } from './replayObservationSceneLogicType'

export const replayObservationSceneLogic = kea<replayObservationSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'observations', 'replayObservationSceneLogic']),

    actions({
        setObservationId: (observationId: string) => ({ observationId }),
        // Pushed by replayObservationLogic once the observation loads, so the breadcrumb can link to its scanner.
        setScannerContext: (scannerId: string | null, scannerName: string | null) => ({ scannerId, scannerName }),
    }),

    reducers({
        observationId: [
            '' as string,
            {
                setObservationId: (_, { observationId }) => observationId,
            },
        ],
        scannerContext: [
            { scannerId: null, scannerName: null } as { scannerId: string | null; scannerName: string | null },
            {
                setScannerContext: (_, { scannerId, scannerName }) => ({ scannerId, scannerName }),
                // Clear when navigating to a different observation so we don't briefly show the previous scanner.
                setObservationId: () => ({ scannerId: null, scannerName: null }),
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.observationId, s.scannerContext],
            (
                observationId: string,
                scannerContext: { scannerId: string | null; scannerName: string | null }
            ): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = [
                    {
                        key: 'replay-vision',
                        name: 'Replay vision',
                        path: urls.replayVision(),
                        iconType: 'replay_vision',
                    },
                ]
                if (scannerContext.scannerId) {
                    breadcrumbs.push({
                        key: `scanner-${scannerContext.scannerId}`,
                        name: scannerContext.scannerName || 'Scanner',
                        path: urls.replayVision(scannerContext.scannerId),
                    })
                }
                breadcrumbs.push({
                    key: observationId ? `observation-${observationId}` : 'observation',
                    name: 'Observation',
                    path: urls.replayVisionObservation(observationId),
                })
                return breadcrumbs
            },
        ],
    }),

    urlToAction(({ actions, values }) => ({
        [urls.replayVisionObservation(':observationId')]: ({ observationId }) => {
            const next = observationId || ''
            if (next !== values.observationId) {
                actions.setObservationId(next)
            }
        },
    })),
])
