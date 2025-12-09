import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { studyDetailsSceneLogicType } from './studyDetailsSceneLogicType'
import { Round, RoundFormValues, Session, Study } from './types'

export interface StudyDetailsSceneLogicProps {
    id: string
}

export const studyDetailsSceneLogic = kea<studyDetailsSceneLogicType>([
    props({} as StudyDetailsSceneLogicProps),
    key(({ id }) => id),
    path((id) => ['products', 'synthetic-users', 'frontend', 'studyDetailsSceneLogic', id]),

    actions({
        setShowNewRoundModal: (show: boolean) => ({ show }),
        setSelectedRoundId: (roundId: string | null) => ({ roundId }),
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

    listeners(({ actions }) => ({
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
        generateSessionsSuccess: () => {
            lemonToast.success('Personas generated')
            actions.loadStudy()
        },
        generateSessionsFailure: ({ error }) => {
            lemonToast.error(`Failed to generate personas: ${error}`)
            actions.loadStudy()
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
    })),

    afterMount(({ actions }) => {
        actions.loadStudy()
    }),
])
