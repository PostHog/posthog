import { actions, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionObservationsLabelCreate, visionObservationsLabelDestroy } from '../generated/api'
import type { ReplayObservationLabelApi } from '../generated/api.schemas'
import type { observationLabelLogicType } from './observationLabelLogicType'

export interface ObservationLabelLogicProps {
    observationId: string
    /** The label as loaded with the observation; seeds the logic state on mount. */
    initialLabel?: ReplayObservationLabelApi | null
    /** Notified after the server accepts a rating change (set or clear). */
    onChange?: (label: ReplayObservationLabelApi | null) => void
}

/** One instance per observation: the team's shared thumbs up/down rating with feedback autosave. */
export const observationLabelLogic = kea<observationLabelLogicType>([
    path(['products', 'replay_vision', 'frontend', 'observations', 'observationLabelLogic']),
    props({} as ObservationLabelLogicProps),
    key((props) => props.observationId),

    actions({
        rate: (isCorrect: boolean, feedback: string) => ({ isCorrect, feedback }),
        clearRating: true,
        labelUpdated: (label: ReplayObservationLabelApi | null) => ({ label }),
        setSaving: (saving: boolean) => ({ saving }),
        setFeedbackDraft: (feedback: string) => ({ feedback }),
    }),

    reducers(({ props }) => ({
        label: [
            (props.initialLabel ?? null) as ReplayObservationLabelApi | null,
            {
                labelUpdated: (_, { label }) => label,
            },
        ],
        saving: [
            false,
            {
                setSaving: (_, { saving }) => saving,
            },
        ],
        feedbackDraft: [
            props.initialLabel?.feedback ?? '',
            {
                setFeedbackDraft: (_, { feedback }) => feedback,
                // Keep the working draft for an active thumbs-down rating so an autosave round-trip can't clobber
                // characters typed while it was in flight; clear it when the rating is removed or flips to thumbs-up.
                labelUpdated: (state, { label }) => (label && label.is_correct === false ? state : ''),
            },
        ],
    })),

    listeners(({ actions, props, cache, values }) => ({
        // Autosave feedback once the user pauses typing, so they don't have to remember to press a button.
        setFeedbackDraft: async ({ feedback }, breakpoint) => {
            const label = values.label
            // Only feedback on an existing thumbs-down rating autosaves; thumbs-up ratings carry none.
            if (!label || label.is_correct !== false || (label.feedback ?? '') === feedback) {
                return
            }
            const epoch = cache.labelEpoch ?? 0
            await breakpoint(800)
            // A thumbs-up/clear click while the debounce was pending wins over the stale autosave.
            if ((cache.labelEpoch ?? 0) !== epoch) {
                return
            }
            actions.rate(false, feedback)
        },

        rate: async ({ isCorrect, feedback }) => {
            cache.labelEpoch = (cache.labelEpoch ?? 0) + 1
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            actions.setSaving(true)
            try {
                const label = await visionObservationsLabelCreate(String(teamId), props.observationId, {
                    is_correct: isCorrect,
                    feedback,
                })
                actions.labelUpdated(label)
                props.onChange?.(label)
            } catch (error: any) {
                lemonToast.error(`Failed to save rating${error.detail ? `: ${error.detail}` : ''}`)
            } finally {
                actions.setSaving(false)
            }
        },

        clearRating: async () => {
            cache.labelEpoch = (cache.labelEpoch ?? 0) + 1
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            actions.setSaving(true)
            try {
                await visionObservationsLabelDestroy(String(teamId), props.observationId)
                actions.labelUpdated(null)
                props.onChange?.(null)
            } catch (error: any) {
                lemonToast.error(`Failed to remove rating${error.detail ? `: ${error.detail}` : ''}`)
            } finally {
                actions.setSaving(false)
            }
        },
    })),
])
