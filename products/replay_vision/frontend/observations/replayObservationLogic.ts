import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionObservationsRetrieve } from '../generated/api'
import type { ReplayObservationApi } from '../generated/api.schemas'
import type { replayObservationLogicType } from './replayObservationLogicType'

export interface ReplayObservationLogicProps {
    id: string
    tabId: string
}

export const replayObservationLogic = kea<replayObservationLogicType>([
    path(['products', 'replay_vision', 'frontend', 'observations', 'replayObservationLogic']),
    props({} as ReplayObservationLogicProps),
    key((props) => `${props.tabId}:${props.id}`),

    actions({
        loadObservation: true,
        loadObservationSuccess: (observation: ReplayObservationApi) => ({ observation }),
        loadObservationFailure: true,
    }),

    reducers({
        observation: [
            null as ReplayObservationApi | null,
            {
                loadObservationSuccess: (_, { observation }) => observation,
            },
        ],
        observationLoading: [
            true,
            {
                loadObservation: () => true,
                loadObservationSuccess: () => false,
                loadObservationFailure: () => false,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        loadObservation: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionObservationsRetrieve(String(teamId), props.id)
                actions.loadObservationSuccess(response)
            } catch (error) {
                lemonToast.error(`Failed to load observation: ${String(error)}`)
                actions.loadObservationFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadObservation()
    }),
])
