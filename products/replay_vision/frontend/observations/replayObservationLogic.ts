import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    visionObservationsLabelCreate,
    visionObservationsLabelDestroy,
    visionObservationsRetrieve,
} from '../generated/api'
import type { ReplayObservationApi, ReplayObservationLabelApi } from '../generated/api.schemas'
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
        setLabel: (isCorrect: boolean, feedback: string) => ({ isCorrect, feedback }),
        clearLabel: true,
        labelUpdated: (label: ReplayObservationLabelApi | null) => ({ label }),
        setLabelSaving: (saving: boolean) => ({ saving }),
        setFeedbackDraft: (feedback: string) => ({ feedback }),
    }),

    reducers({
        observation: [
            null as ReplayObservationApi | null,
            {
                loadObservationSuccess: (_, { observation }) => observation,
                labelUpdated: (state, { label }) => (state ? { ...state, label } : state),
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
        labelSaving: [
            false,
            {
                setLabelSaving: (_, { saving }) => saving,
            },
        ],
        feedbackDraft: [
            '',
            {
                setFeedbackDraft: (_, { feedback }) => feedback,
                // Seed from the saved label on first load, but don't clobber in-progress typing on later reloads.
                loadObservationSuccess: (state, { observation }) => state || (observation.label?.feedback ?? ''),
                // Keep the working draft for an active "incorrect" label so an autosave round-trip can't clobber
                // characters typed while it was in flight; clear it when the label is removed or set to correct.
                labelUpdated: (state, { label }) => (label && label.is_correct === false ? state : ''),
            },
        ],
    }),

    listeners(({ actions, props, cache, values }) => ({
        // Autosave feedback once the user pauses typing, so they don't have to remember to press a button.
        setFeedbackDraft: async ({ feedback }, breakpoint) => {
            const label = values.observation?.label
            // Only feedback on an existing "incorrect" label autosaves; correct labels carry none.
            if (!label || label.is_correct !== false || (label.feedback ?? '') === feedback) {
                return
            }
            await breakpoint(800)
            actions.setLabel(false, feedback)
        },

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

        setLabel: async ({ isCorrect, feedback }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            actions.setLabelSaving(true)
            try {
                const label = await visionObservationsLabelCreate(String(teamId), props.id, {
                    is_correct: isCorrect,
                    feedback,
                })
                actions.labelUpdated(label)
            } catch (error: any) {
                lemonToast.error(`Failed to save label${error.detail ? `: ${error.detail}` : ''}`)
            } finally {
                actions.setLabelSaving(false)
            }
        },

        clearLabel: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            actions.setLabelSaving(true)
            try {
                await visionObservationsLabelDestroy(String(teamId), props.id)
                actions.labelUpdated(null)
            } catch (error: any) {
                lemonToast.error(`Failed to remove label${error.detail ? `: ${error.detail}` : ''}`)
            } finally {
                actions.setLabelSaving(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadObservation()
    }),
])
