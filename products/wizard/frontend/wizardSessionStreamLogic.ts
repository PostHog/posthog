import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import {
    createPollLoop,
    isPermanentPollError,
    resolvePollingIntervalMs,
    resolveWizardSyncMode,
    type WizardSyncMode,
} from 'lib/wizard-sync/pollLoop'
import { logSyncDebug } from 'lib/wizard-sync/wizardSyncDebugLogic'
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
 * EventSource is replaced by a poll loop that re-fetches the latest session via
 * `wizard/sessions/latest/` and feeds it through the same `sessionUpdated` action.
 * The loop (shared with `taskRunStreamLogic`) backs off on consecutive errors, stops on
 * permanent ones (401/403/404), and backs off on consecutive empty responses — so an
 * endpoint with no session (not started yet, or killswitched to 204) winds down instead
 * of being polled at full cadence forever. Consumers stop it via `disconnect`;
 * `installationProgressLogic` does so once a cloud run reaches a terminal state.
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

            // Mode is re-sampled on every connect, and the setFeatureFlags listener below reconnects
            // when the resolved mode changes — so a flag flip (or flags arriving after a cold-cache
            // connect) swaps the transport live instead of waiting for a remount.
            const syncMode: WizardSyncMode = resolveWizardSyncMode(
                values.featureFlags[FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC_MODE]
            )
            cache.syncMode = syncMode

            if (syncMode === 'polling') {
                const intervalMs = resolvePollingIntervalMs(
                    getFeatureFlagPayload(FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC_MODE)
                )
                logSyncDebug(debugSource, 'connect', `polling every ~${intervalMs / 1000}s (±20% jitter)`, {
                    mode: 'polling',
                    intervalMs,
                })
                cache.disposables.add(
                    createPollLoop({
                        intervalMs,
                        tick: async () => {
                            // 204 (no session yet, or killswitched) resolves to null — classify as
                            // empty so the loop backs off instead of polling at full cadence forever.
                            const session = await wizardSessionsLatestRetrieve(String(projectId), {
                                workflow_id: props.workflowId,
                                skill_id: props.skillId,
                            })
                            logSyncDebug(
                                debugSource,
                                'poll',
                                session
                                    ? `poll ok: ${session.run_phase} (${session.skill_id})`
                                    : 'poll ok: no session yet',
                                { mode: 'polling', intervalMs }
                            )
                            // Only on first open / recovery from error — not every tick.
                            if (values.connectionStatus !== 'open') {
                                actions.connectionOpened()
                            }
                            if (!session) {
                                return 'empty'
                            }
                            actions.sessionUpdated(session)
                            return 'ok'
                        },
                        onError: (err) => {
                            logSyncDebug(debugSource, 'error', `poll failed: ${String(err)}`)
                            actions.connectionErrored(`Failed to poll wizard session: ${String(err)}`)
                            return isPermanentPollError(err) ? 'stop' : 'retry'
                        },
                        // Dispose the key so a later tab-visibility resume doesn't restart a loop
                        // that ended itself.
                        onLoopEnd: () => cache.disposables.dispose('session-sync'),
                    }),
                    'session-sync'
                )
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
        // Flags can resolve after a cold-cache connect (posthog-js loads them async), and ops can flip
        // the mode mid-incident. Reconnect when the resolved mode differs from the running transport —
        // the keyed disposable makes the swap idempotent.
        [featureFlagLogic.actionTypes.setFeatureFlags]: () => {
            if (cache.syncMode === undefined) {
                return
            }
            if (values.connectionStatus === 'idle' || values.connectionStatus === 'closed') {
                return
            }
            const mode = resolveWizardSyncMode(values.featureFlags[FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC_MODE])
            if (mode !== cache.syncMode) {
                actions.connect()
            }
        },
    })),
])
