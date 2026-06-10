import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import { getWizardSessionsStreamRetrieveUrl } from './generated/api'
import type { WizardSessionDTOApi } from './generated/api.schemas'
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
    path((key) => ['products', 'wizard', 'wizardSessionStreamLogic', key]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        connect: true,
        disconnect: true,
        sessionUpdated: (session: WizardSessionDTOApi) => ({ session }),
        connectionOpened: true,
        connectionErrored: (error: string) => ({ error }),
    }),
    reducers({
        latestSession: [
            null as WizardSessionDTOApi | null,
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
                const url = getWizardSessionsStreamRetrieveUrl(String(projectId), {
                    workflow_id: props.workflowId,
                    skill_id: props.skillId,
                })
                const eventSource = new EventSource(url, { withCredentials: true })

                eventSource.onopen = actions.connectionOpened
                eventSource.onmessage = (event: MessageEvent<string>): void => {
                    try {
                        const session = JSON.parse(event.data) as WizardSessionDTOApi
                        actions.sessionUpdated(session)
                    } catch (err) {
                        actions.connectionErrored(`Failed to parse SSE payload: ${String(err)}`)
                    }
                }
                eventSource.onerror = (): void => {
                    // EventSource readyState distinguishes terminal close vs transient retry:
                    //   CLOSED (2)     → browser gave up; will NOT auto-reconnect.
                    //                    Consumers must call connect() again.
                    //   CONNECTING (0) → browser is already retrying; ride it out, surface
                    //                    the state so the UI can show "reconnecting".
                    if (eventSource.readyState === EventSource.CLOSED) {
                        actions.connectionErrored('EventSource connection closed by server — call connect() to retry')
                    } else {
                        actions.connectionErrored('EventSource transport error — reconnecting')
                    }
                }

                return () => eventSource.close()
            }, 'event-source')
        },
        disconnect: () => {
            cache.disposables.dispose('event-source')
        },
    })),
])
