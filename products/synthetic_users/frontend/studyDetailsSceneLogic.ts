import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { studyDetailsSceneLogicType } from './studyDetailsSceneLogicType'
import { Round, RoundFormValues, Session, Study } from './types'

export interface StudyDetailsSceneLogicProps {
    id: string
}

const POLL_INTERVAL_MS = 2000

export const studyDetailsSceneLogic = kea<studyDetailsSceneLogicType>([
    props({} as StudyDetailsSceneLogicProps),
    key(({ id }) => id),
    path((id) => ['products', 'synthetic-users', 'frontend', 'studyDetailsSceneLogic', id]),

    actions({
        setShowNewRoundModal: (show: boolean) => ({ show }),
        setSelectedRoundId: (roundId: string | null) => ({ roundId }),
        startPolling: true,
        stopPolling: true,
        generateSessionsWithPolling: (roundId: string) => ({ roundId }),
    }),

    reducers({
        showNewRoundModal: [
            false,
            {
                setShowNewRoundModal: (_, { show }) => show,
            },
        ],
        selectedRoundId: [
            null as string | null,
            {
                setSelectedRoundId: (_, { roundId }) => roundId,
            },
        ],
        pollingIntervalId: [
            null as number | null,
            {
                startPolling: (state) => state, // Handled in listener
                stopPolling: () => null,
            },
        ],
    }),

    loaders(({ props }) => ({
        study: [
            null as Study | null,
            {
                loadStudy: async () => {
                    const response = await api.syntheticUsers.getStudy(props.id)
                    return response.study
                },
            },
        ],
        createdRound: [
            null as Round | null,
            {
                createRound: async (formValues: RoundFormValues) => {
                    const response = await api.syntheticUsers.createRound({
                        study_id: props.id,
                        session_count: formValues.session_count,
                        notes: formValues.notes || undefined,
                    })
                    return response.round
                },
            },
        ],
        generatedRound: [
            null as Round | null,
            {
                generateSessions: async (roundId: string) => {
                    const response = await api.syntheticUsers.generateSessions(roundId)
                    return response.round
                },
            },
        ],
        startedRound: [
            null as Round | null,
            {
                startRound: async (roundId: string) => {
                    const response = await api.syntheticUsers.startRound(roundId)
                    return response.round
                },
            },
        ],
        regeneratedSession: [
            null as Session | null,
            {
                regenerateSession: async (sessionId: string) => {
                    const response = await api.syntheticUsers.regenerateSession(sessionId)
                    return response.session
                },
            },
        ],
        startedSession: [
            null as Session | null,
            {
                startSession: async (sessionId: string) => {
                    const response = await api.syntheticUsers.startSession(sessionId)
                    return response.session
                },
            },
        ],
    })),

    forms(({ actions }) => ({
        roundForm: {
            defaults: {
                session_count: 5,
                notes: '',
            } as RoundFormValues,
            errors: ({ session_count }) => ({
                session_count:
                    !session_count || session_count < 1
                        ? 'At least 1 session is required'
                        : session_count > 20
                          ? 'Maximum 20 sessions per round'
                          : undefined,
            }),
            submit: async (formValues) => {
                actions.createRound(formValues)
            },
        },
    })),

    listeners(({ actions, cache }) => ({
        createRoundSuccess: ({ createdRound }) => {
            lemonToast.success('Round created')
            actions.resetRoundForm()
            actions.setShowNewRoundModal(false)
            if (createdRound) {
                actions.setSelectedRoundId(createdRound.id)
            }
            actions.loadStudy()
        },
        createRoundFailure: ({ error }) => {
            lemonToast.error(`Failed to create round: ${error}`)
        },
        generateSessionsWithPolling: ({ roundId }) => {
            // Start polling immediately, then kick off generation
            actions.startPolling()
            actions.generateSessions(roundId)
        },
        generateSessionsSuccess: () => {
            actions.stopPolling()
            lemonToast.success('Personas generated')
            actions.loadStudy()
        },
        generateSessionsFailure: ({ error }) => {
            actions.stopPolling()
            lemonToast.error(`Failed to generate personas: ${error}`)
            actions.loadStudy()
        },
        startPolling: () => {
            // Clear any existing interval
            if (cache.pollingIntervalId) {
                clearInterval(cache.pollingIntervalId)
            }
            cache.pollingIntervalId = setInterval(() => {
                actions.loadStudy()
            }, POLL_INTERVAL_MS)
        },
        stopPolling: () => {
            if (cache.pollingIntervalId) {
                clearInterval(cache.pollingIntervalId)
                cache.pollingIntervalId = null
            }
        },
        startRoundSuccess: () => {
            lemonToast.success('Round started')
            actions.loadStudy()
        },
        startRoundFailure: ({ error }) => {
            lemonToast.error(`Failed to start round: ${error}`)
        },
        regenerateSessionSuccess: () => {
            lemonToast.success('Persona regenerated')
            actions.loadStudy()
        },
        regenerateSessionFailure: ({ error }) => {
            lemonToast.error(`Failed to regenerate persona: ${error}`)
        },
        startSessionSuccess: () => {
            lemonToast.success('Session started')
            actions.loadStudy()
        },
        startSessionFailure: ({ error }) => {
            lemonToast.error(`Failed to start session: ${error}`)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadStudy()
    }),

    beforeUnmount(({ cache }) => {
        // Clean up polling on unmount
        if (cache.pollingIntervalId) {
            clearInterval(cache.pollingIntervalId)
        }
    }),
])
