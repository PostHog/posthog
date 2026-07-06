import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import {
    jitteredIntervalMs,
    resolvePollingIntervalMs,
    type WizardSyncMode,
} from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/taskRunStreamLogic'
import { logSyncDebug } from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/WizardSync/wizardSyncDebugLogic'
import { projectLogic } from 'scenes/projectLogic'

import { getWizardSessionsStreamRetrieveUrl, wizardSessionsLatestRetrieve } from './generated/api'
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
 * When the `onboarding-wizard-sync-mode` flag resolves to `polling` (GROW-118), the
 * EventSource is replaced by an interval that re-fetches the latest session via
 * `wizard/sessions/latest/` and feeds it through the same `sessionUpdated` action —
 * mirroring `taskRunStreamLogic`, whose interval/jitter helpers this reuses. Like SSE,
 * polling runs until `disconnect` (sessions have no terminal state to stop on).
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
        values: [projectLogic, ['currentProjectId'], featureFlagLogic, ['featureFlags']],
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

            const debugSource = `session ${props.workflowId}::${props.skillId ?? '*'}`

            // Mode is sampled once per connect — a mid-run flag flip applies on the next (re)connect,
            // not live, which keeps the transport swap trivially safe.
            const syncMode: WizardSyncMode =
                values.featureFlags[FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC_MODE] === 'polling' ? 'polling' : 'sse'

            if (syncMode === 'polling') {
                const intervalMs = resolvePollingIntervalMs(
                    getFeatureFlagPayload(FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC_MODE)
                )
                logSyncDebug(debugSource, 'connect', `polling every ~${intervalMs / 1000}s (±20% jitter)`, {
                    mode: 'polling',
                    intervalMs,
                })
                cache.disposables.add((): (() => void) => {
                    let cancelled = false
                    let timer: number | undefined
                    // Each tick schedules the next one only after its request settles, so a slow
                    // server can never stack requests, and every gap gets fresh jitter.
                    const poll = async (): Promise<void> => {
                        try {
                            // 204 (no session yet) resolves to undefined — keep polling until one appears.
                            const session = await wizardSessionsLatestRetrieve(String(projectId), {
                                workflow_id: props.workflowId,
                                skill_id: props.skillId,
                            })
                            if (cancelled) {
                                return
                            }
                            logSyncDebug(
                                debugSource,
                                'poll',
                                session
                                    ? `poll ok — ${session.run_phase} (${session.skill_id})`
                                    : 'poll ok — no session yet',
                                { mode: 'polling', intervalMs }
                            )
                            // Only on first open / recovery from error — not every tick.
                            if (values.connectionStatus !== 'open') {
                                actions.connectionOpened()
                            }
                            if (session) {
                                actions.sessionUpdated(session)
                            }
                        } catch (err) {
                            if (cancelled) {
                                return
                            }
                            logSyncDebug(debugSource, 'error', `poll failed: ${String(err)}`)
                            actions.connectionErrored(`Failed to poll wizard session: ${String(err)}`)
                        }
                        timer = window.setTimeout(() => void poll(), jitteredIntervalMs(intervalMs))
                    }
                    void poll()
                    return () => {
                        cancelled = true
                        window.clearTimeout(timer)
                    }
                }, 'session-sync')
                return
            }

            logSyncDebug(debugSource, 'connect', 'opening EventSource', { mode: 'sse' })
            cache.disposables.add((): (() => void) => {
                const url = getWizardSessionsStreamRetrieveUrl(String(projectId), {
                    workflow_id: props.workflowId,
                    skill_id: props.skillId,
                })
                const eventSource = new EventSource(url, { withCredentials: true })

                eventSource.onopen = (): void => {
                    // Mode rides along here too: the connect event can predate the debug panel's
                    // mount (and get dropped), but open/events always land after it.
                    logSyncDebug(debugSource, 'open', 'SSE connection open', { mode: 'sse' })
                    actions.connectionOpened()
                }
                eventSource.onmessage = (event: MessageEvent<string>): void => {
                    try {
                        const session = JSON.parse(event.data) as WizardSessionDTOApi
                        logSyncDebug(debugSource, 'event', `session → ${session.run_phase} (${session.skill_id})`, {
                            mode: 'sse',
                        })
                        actions.sessionUpdated(session)
                    } catch (err) {
                        logSyncDebug(debugSource, 'error', `failed to parse SSE payload: ${String(err)}`)
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
                        logSyncDebug(debugSource, 'error', 'SSE closed by server')
                        actions.connectionErrored('EventSource connection closed by server — call connect() to retry')
                    } else {
                        logSyncDebug(debugSource, 'error', 'SSE transport error — reconnecting')
                        actions.connectionErrored('EventSource transport error — reconnecting')
                    }
                }

                return () => eventSource.close()
            }, 'session-sync')
        },
        disconnect: () => {
            logSyncDebug(`session ${props.workflowId}::${props.skillId ?? '*'}`, 'disconnect', 'disconnected')
            cache.disposables.dispose('session-sync')
        },
    })),
])
