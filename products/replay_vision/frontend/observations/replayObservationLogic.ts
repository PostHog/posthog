import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { visionObservationsRetrieve } from '../generated/api'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { scheduleObservationPoll } from '../logics/observationPolling'
import { requestObservationRetry } from '../logics/observationRetry'
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
        retryObservation: true,
        retryObservationSuccess: true,
        retryObservationFailure: true,
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
        retrying: [
            false,
            {
                retryObservation: () => true,
                retryObservationSuccess: () => false,
                retryObservationFailure: () => false,
            },
        ],
    }),

    listeners(({ actions, props, values, cache }) => {
        // Poll while in flight as the SSE fallback, on failure too; reducers run first, so `observation` is current.
        const reschedulePoll = (): void => {
            const inFlight = values.observation?.status === 'pending' || values.observation?.status === 'running'
            scheduleObservationPoll(cache.disposables, inFlight, actions.loadObservation)
        }
        return {
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
                    // Only toast the initial load — background poll retries would otherwise spam one toast per tick.
                    if (!values.observation) {
                        lemonToast.error(`Failed to load observation${error.detail ? `: ${error.detail}` : ''}`)
                    }
                    actions.loadObservationFailure()
                }
            },

            loadObservationSuccess: reschedulePoll,
            loadObservationFailure: reschedulePoll,

            retryObservation: async () => {
                const retried = await requestObservationRetry(
                    props.id,
                    'Retrying scan — the new observation will appear on the scanner page shortly.'
                )
                if (!retried) {
                    actions.retryObservationFailure()
                    return
                }
                actions.retryObservationSuccess()
                // The retried row is deleted, so this page's id now dangles — hand off to the scanner.
                const scannerId = values.observation?.scanner_id
                if (scannerId) {
                    router.actions.push(urls.replayVision(scannerId))
                }
            },

            // When the stream reports the observation has settled, reload once to render the final result.
            streamCompleted: () => {
                actions.loadObservation()
            },
        }
    }),

    afterMount(({ actions }) => {
        actions.loadObservation()
    }),
])
