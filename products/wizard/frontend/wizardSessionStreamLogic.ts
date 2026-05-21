import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import type { WizardSessionApi } from './generated/api.schemas'
import type { wizardSessionStreamLogicType } from './wizardSessionStreamLogicType'

export type WizardConnectionStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

export interface WizardSessionStreamLogicProps {
    workflowId: string
    /**
     * Optional. When omitted, the backend pattern-subscribes to all skills under
     * the workflow. Useful when the framework / skill the wizard will run isn't
     * known up front (the common onboarding case).
     */
    skillId?: string
}

/**
 * Subscribes to the SSE stream for a wizard workflow (optionally a specific skill)
 * and exposes the latest WizardSession state plus connection status.
 *
 * Each (workflowId, skillId) pair gets its own logic instance keyed by props, so
 * multiple subscriptions coexist in the app. Omitting skillId pattern-subscribes
 * to every skill under the workflow.
 *
 * Usage:
 *
 *   // Listen to any skill under the posthog-integration workflow:
 *   const { latestSession } = useValues(
 *       wizardSessionStreamLogic({ workflowId: 'posthog-integration' })
 *   )
 *
 *   // Or pin to one skill:
 *   const { latestSession } = useValues(
 *       wizardSessionStreamLogic({ workflowId: 'posthog-integration', skillId: 'nextjs' })
 *   )
 */
export const wizardSessionStreamLogic = kea<wizardSessionStreamLogicType>([
    props({} as WizardSessionStreamLogicProps),
    key((props) => `${props.workflowId}::${props.skillId ?? '*'}`),
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
                const params = new URLSearchParams({ workflow_id: props.workflowId })
                if (props.skillId) {
                    params.set('skill_id', props.skillId)
                }
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
