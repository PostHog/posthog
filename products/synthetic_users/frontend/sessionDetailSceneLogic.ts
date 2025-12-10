import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { sessionDetailSceneLogicType } from './sessionDetailSceneLogicType'
import type { ParticipantStatus } from './types'
import { Session, Study } from './types'

export interface SessionDetailSceneLogicProps {
    studyId: string
    sessionId: string
}

const POLL_INTERVAL_MS = 2000
const IN_PROGRESS_STATUSES: ParticipantStatus[] = ['generating', 'navigating']

export const sessionDetailSceneLogic = kea<sessionDetailSceneLogicType>([
    props({} as SessionDetailSceneLogicProps),
    key(({ studyId, sessionId }) => `${studyId}-${sessionId}`),
    path((key) => ['products', 'synthetic-users', 'frontend', 'sessionDetailSceneLogic', key]),

    actions({
        setSession: (session: Session) => ({ session }),
        startPolling: true,
        stopPolling: true,
    }),

    reducers({
        session: [
            null as Session | null,
            {
                setSession: (_, { session }) => session,
            },
        ],
    }),

    selectors({
        shouldPoll: [
            (s) => [s.session],
            (session): boolean => {
                if (!session) {
                    return false
                }
                return IN_PROGRESS_STATUSES.includes(session.status)
            },
        ],
    }),

    loaders(({ props, actions }) => ({
        study: [
            null as Study | null,
            {
                loadStudy: async () => {
                    const response = await api.syntheticUsers.getStudy(props.studyId)
                    const study = response.study
                    // Extract session from study data
                    if (study?.rounds) {
                        for (const round of study.rounds) {
                            const session = round.sessions?.find((s: Session) => s.id === props.sessionId)
                            if (session) {
                                actions.setSession(session)
                                break
                            }
                        }
                    }
                    return study
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

    listeners(({ actions, values, cache }) => ({
        regenerateSessionSuccess: ({ regeneratedSession }) => {
            lemonToast.success('Persona regenerated')
            if (regeneratedSession) {
                actions.setSession(regeneratedSession)
            }
            actions.loadStudy()
        },
        regenerateSessionFailure: ({ error }) => {
            lemonToast.error(`Failed to regenerate persona: ${error}`)
        },
        startSessionSuccess: ({ startedSession }) => {
            lemonToast.success('Session started')
            if (startedSession) {
                actions.setSession(startedSession)
            }
            actions.loadStudy()
            // Start polling since session is now in progress
            actions.startPolling()
        },
        startSessionFailure: ({ error }) => {
            lemonToast.error(`Failed to start session: ${error}`)
        },
        setSession: () => {
            // Check if we should start or stop polling based on new session state
            if (values.shouldPoll) {
                actions.startPolling()
            } else {
                actions.stopPolling()
            }
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
