import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import type { WizardSessionApi } from './generated/api.schemas'
import type { wizardSessionStreamLogicType } from './wizardSessionStreamLogicType'

export type WizardConnectionStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

export interface WizardSessionStreamLogicProps {
    workflowId: string
    skillId: string
}

/**
 * Subscribes to the SSE stream for a (workflow_id, skill_id) pair and exposes the
 * latest WizardSession state plus connection status to consumers.
 *
 * Each (workflowId, skillId) gets its own logic instance (keyed by props), so
 * multiple subscriptions for different streams can coexist in the app.
 *
 * Usage:
 *
 *   const { latestSession, connectionStatus } = useValues(
 *       wizardSessionStreamLogic({ workflowId: 'onboarding', skillId: 'nextjs' })
 *   )
 *   const { connect, disconnect } = useActions(
 *       wizardSessionStreamLogic({ workflowId: 'onboarding', skillId: 'nextjs' })
 *   )
 *
 * Nothing in the app calls this yet — it's the plumbing for downstream features
 * (e.g. wizard-aware onboarding scene).
 */
export const wizardSessionStreamLogic = kea<wizardSessionStreamLogicType>([
    props({} as WizardSessionStreamLogicProps),
    key((props) => `${props.workflowId}::${props.skillId}`),
    path((key) => ['products', 'wizard', 'streams', key]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        connect: true,
        disconnect: true,
        sessionUpdated: (session: WizardSessionApi) => ({ session }),
        connectionOpened: true,
        connectionErrored: (error: string) => ({ error }),
    }),
    reducers({
        latestSession: [
            null as WizardSessionApi | null,
            {
                sessionUpdated: (_, { session }) => session,
            },
        ],
        connectionStatus: [
            'idle' as WizardConnectionStatus,
            {
                connect: () => 'connecting',
                connectionOpened: () => 'open',
                connectionErrored: () => 'error',
                disconnect: () => 'closed',
            },
        ],
        lastError: [
            null as string | null,
            {
                connect: () => null,
                sessionUpdated: () => null,
                connectionErrored: (_, { error }) => error,
            },
        ],
    }),
    listeners(({ values, actions, props, cache }) => ({
        connect: () => {
            const projectId = values.currentProjectId
            if (projectId === null) {
                actions.connectionErrored('No current project — cannot open wizard session stream.')
                return
            }

            cache.disposables.add((): (() => void) => {
                const params = new URLSearchParams({
                    workflow_id: props.workflowId,
                    skill_id: props.skillId,
                })
                const url = `/api/projects/${projectId}/wizard_sessions/stream/?${params.toString()}`
                const eventSource = new EventSource(url, { withCredentials: true })

                eventSource.onopen = (): void => {
                    actions.connectionOpened()
                }
                eventSource.onmessage = (event: MessageEvent<string>): void => {
                    try {
                        const session = JSON.parse(event.data) as WizardSessionApi
                        actions.sessionUpdated(session)
                    } catch (err) {
                        actions.connectionErrored(`Failed to parse SSE payload: ${String(err)}`)
                    }
                }
                eventSource.onerror = (): void => {
                    // EventSource reconnects automatically on transient errors; we surface
                    // the state so consumers can show a "reconnecting" UI if desired.
                    actions.connectionErrored('EventSource transport error')
                }

                return () => eventSource.close()
            }, 'event-source')
        },
        disconnect: () => {
            cache.disposables.dispose('event-source')
        },
    })),
])
