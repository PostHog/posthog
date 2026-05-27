import { actions, kea, path, props, reducers, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { replayObservationSceneLogicType } from './replayObservationSceneLogicType'

export interface ReplayObservationSceneLogicProps {
    tabId: string
}

export const replayObservationSceneLogic = kea<replayObservationSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'observations', 'replayObservationSceneLogic']),
    props({} as ReplayObservationSceneLogicProps),
    tabAwareScene(),

    actions({
        setObservationId: (observationId: string) => ({ observationId }),
    }),

    reducers({
        observationId: [
            '' as string,
            {
                setObservationId: (_, { observationId }) => observationId,
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.observationId],
            (observationId: string): Breadcrumb[] => [
                {
                    key: 'replay-vision',
                    name: 'Replay vision',
                    path: urls.replayVision(),
                    iconType: 'replay_vision',
                },
                {
                    key: observationId ? `observation-${observationId}` : 'observation',
                    name: 'Observation',
                    path: urls.replayVisionObservation(observationId),
                },
            ],
        ],
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.replayVisionObservation(':observationId')]: ({ observationId }) => {
            const next = observationId || ''
            if (next !== values.observationId) {
                actions.setObservationId(next)
            }
        },
    })),
])
