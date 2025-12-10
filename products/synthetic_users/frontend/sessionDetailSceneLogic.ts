import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { sessionDetailSceneLogicType } from './sessionDetailSceneLogicType'
import { Session, Study } from './types'

export interface SessionDetailSceneLogicProps {
    studyId: string
    sessionId: string
}

export const sessionDetailSceneLogic = kea<sessionDetailSceneLogicType>([
    props({} as SessionDetailSceneLogicProps),
    key(({ studyId, sessionId }) => `${studyId}-${sessionId}`),
    path((key) => ['products', 'synthetic-users', 'frontend', 'sessionDetailSceneLogic', key]),

    actions({
        setSession: (session: Session) => ({ session }),
    }),

    reducers({
        session: [
            null as Session | null,
            {
                setSession: (_, { session }) => session,
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
                            const session = round.sessions?.find((s) => s.id === props.sessionId)
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

    listeners(({ actions }) => ({
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
        },
        startSessionFailure: ({ error }) => {
            lemonToast.error(`Failed to start session: ${error}`)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadStudy()
    }),
])
