import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionObservationsRetrieve } from '../generated/api'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { scheduleObservationPoll } from '../logics/observationPolling'
import { observationProgressLogic } from './observationProgressLogic'
import type { replayObservationLogicType } from './replayObservationLogicType'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

export interface ReplayObservationLogicProps {
    id: string
}

export const replayObservationLogic = kea<replayObservationLogicType>([
    path(['products', 'replay_vision', 'frontend', 'observations', 'replayObservationLogic']),
    props({} as ReplayObservationLogicProps),
    key((props) => props.id),

    // Mount the SSE progress stream alongside the page and listen for its completion to reload the row.
    connect((props: ReplayObservationLogicProps) => ({
        actions: [observationProgressLogic({ observationId: props.id }), ['streamCompleted']],
    })),

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

    listeners(({ actions, props, cache }) => ({
        loadObservation: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionObservationsRetrieve(String(teamId), props.id)
                actions.loadObservationSuccess(response)
                // Link the breadcrumb to the parent scanner so "back" returns to the scanner, not the vision home.
                replayObservationSceneLogic().actions.setScannerContext(
                    response.scanner_id,
                    response.scanner_snapshot?.name ?? null
                )
            } catch (error: any) {
                lemonToast.error(`Failed to load observation${error.detail ? `: ${error.detail}` : ''}`)
                actions.loadObservationFailure()
            }
        },

        loadObservationSuccess: ({ observation }) => {
            // SSE flips us to the result instantly when our listener catches `streamCompleted`, but the
            // stream is a shared keyed logic — if the dock started and finished it before this page opened,
            // the past event isn't replayed here. Poll while in flight as a fallback so we still land the result.
            const inFlight = observation.status === 'pending' || observation.status === 'running'
            scheduleObservationPoll(cache.disposables, inFlight, actions.loadObservation)
        },

        // When the stream reports the observation has settled, reload once to render the final result.
        streamCompleted: () => {
            actions.loadObservation()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadObservation()
    }),
])
