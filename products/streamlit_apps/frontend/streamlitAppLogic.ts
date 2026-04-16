import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { streamlitAppLogicType } from './streamlitAppLogicType'
import { StreamlitAppSandbox, StreamlitAppStatus, StreamlitAppType, StreamlitConnectInfo } from './types'

export interface StreamlitAppLogicProps {
    shortId: string
}

const POLL_INTERVAL_MS = 2000
const HEALTH_POLL_INTERVAL_MS = 15000
const TOKEN_REFRESH_RATIO = 0.8 // refresh at 80% of expiry
// Floor prevents a malformed expires_in from scheduling an immediate refresh loop.
const MIN_TOKEN_REFRESH_MS = 5_000

type TimerKey = 'pollTimer' | 'healthPollTimer' | 'tokenRefreshTimer'

export const streamlitAppLogic = kea<streamlitAppLogicType>([
    path(['products', 'streamlit_apps', 'frontend', 'streamlitAppLogic']),
    props({} as StreamlitAppLogicProps),
    key((props) => props.shortId),

    actions({
        startPolling: true,
        stopPolling: true,
        startHealthPolling: true,
        stopHealthPolling: true,
        scheduleTokenRefresh: (expiresIn: number) => ({ expiresIn }),
        clearTokenRefresh: true,
    }),

    loaders(({ props }) => ({
        streamlitApp: [
            null as StreamlitAppType | null,
            {
                loadStreamlitApp: async () => {
                    return await api.streamlitApps.get(props.shortId)
                },
            },
        ],
        sandboxStatus: [
            null as StreamlitAppSandbox | null,
            {
                loadSandboxStatus: async () => {
                    return await api.streamlitApps.status(props.shortId)
                },
                startApp: async () => {
                    const app = await api.streamlitApps.start(props.shortId)
                    return app.sandbox ?? null
                },
                stopApp: async () => {
                    const app = await api.streamlitApps.stop(props.shortId)
                    return app.sandbox ?? null
                },
                restartApp: async () => {
                    const app = await api.streamlitApps.restart(props.shortId)
                    return app.sandbox ?? null
                },
            },
        ],
        connectInfo: [
            null as StreamlitConnectInfo | null,
            {
                loadConnectInfo: async () => {
                    return await api.streamlitApps.connectInfo(props.shortId)
                },
            },
        ],
    })),

    reducers({
        isPolling: [
            false,
            {
                startPolling: () => true,
                stopPolling: () => false,
            },
        ],
        isHealthPolling: [
            false,
            {
                startHealthPolling: () => true,
                stopHealthPolling: () => false,
            },
        ],
        connectError: [
            null as string | null,
            {
                loadConnectInfoFailure: (_, { error }) => String(error),
                loadConnectInfoSuccess: () => null,
                startApp: () => null,
                restartApp: () => null,
            },
        ],
        connectInfo: {
            // Restart mints a new sandbox — clear so we refetch fresh tokens.
            restartApp: () => null,
            restartAppSuccess: () => null,
        },
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.streamlitApp],
            (streamlitApp): Breadcrumb[] => [
                {
                    key: 'StreamlitApps',
                    name: 'Apps',
                    path: urls.streamlitApps(),
                },
                {
                    key: ['StreamlitApp', streamlitApp?.short_id || 'new'],
                    name: streamlitApp?.name || 'Loading...',
                },
            ],
        ],
        appStatus: [
            (s) => [s.sandboxStatus],
            (sandboxStatus): StreamlitAppStatus => sandboxStatus?.status ?? 'stopped',
        ],
        iframeSrc: [
            (s) => [s.appStatus, s.connectInfo],
            (appStatus, connectInfo): string | null => {
                if (appStatus !== 'running' || !connectInfo) {
                    return null
                }
                return connectInfo.iframe_url
            },
        ],
    }),

    listeners(({ actions, values, cache }) => {
        // Idempotent clear — kea listeners can fire multiple times and timers
        // would otherwise stack. clearInterval accepts timeout IDs too, so one
        // helper covers both setInterval and setTimeout.
        const clearCached = (key: TimerKey): void => {
            if (cache[key]) {
                clearInterval(cache[key])
                cache[key] = null
            }
        }
        return {
            loadStreamlitAppSuccess: ({ streamlitApp }) => {
                if (!streamlitApp) {
                    return
                }
                // Seed sandboxStatus from app data so appStatus is correct immediately.
                if (streamlitApp.sandbox) {
                    actions.loadSandboxStatusSuccess(streamlitApp.sandbox)
                }
                const status = streamlitApp.sandbox?.status ?? 'stopped'
                if (status === 'starting') {
                    actions.startPolling()
                } else if (status === 'running') {
                    actions.loadConnectInfo()
                }
            },
            startAppSuccess: () => {
                actions.startPolling()
            },
            startPolling: () => {
                clearCached('pollTimer')
                cache.pollTimer = setInterval(() => {
                    actions.loadSandboxStatus()
                }, POLL_INTERVAL_MS)
            },
            stopPolling: () => clearCached('pollTimer'),
            startHealthPolling: () => {
                clearCached('healthPollTimer')
                cache.healthPollTimer = setInterval(() => {
                    actions.loadSandboxStatus()
                }, HEALTH_POLL_INTERVAL_MS)
            },
            stopHealthPolling: () => clearCached('healthPollTimer'),
            loadSandboxStatusSuccess: ({ sandboxStatus }) => {
                if (!sandboxStatus) {
                    return
                }
                if (sandboxStatus.status === 'running') {
                    actions.stopPolling()
                    if (!values.isHealthPolling) {
                        actions.startHealthPolling()
                    }
                    if (!values.connectInfo) {
                        actions.loadConnectInfo()
                    }
                } else if (sandboxStatus.status === 'error' || sandboxStatus.status === 'stopped') {
                    actions.stopPolling()
                    actions.stopHealthPolling()
                    actions.clearTokenRefresh()
                }
            },
            loadConnectInfoSuccess: ({ connectInfo }) => {
                if (connectInfo) {
                    actions.scheduleTokenRefresh(connectInfo.expires_in)
                }
            },
            scheduleTokenRefresh: ({ expiresIn }) => {
                actions.clearTokenRefresh()
                const refreshMs = Math.max(expiresIn * TOKEN_REFRESH_RATIO * 1000, MIN_TOKEN_REFRESH_MS)
                cache.tokenRefreshTimer = setTimeout(() => {
                    actions.loadConnectInfo()
                }, refreshMs)
            },
            loadConnectInfoFailure: () => {
                // Don't reschedule — a 5s retry loop would hammer a broken sandbox.
                actions.clearTokenRefresh()
            },
            clearTokenRefresh: () => clearCached('tokenRefreshTimer'),
            stopAppSuccess: () => {
                actions.stopPolling()
                actions.stopHealthPolling()
                actions.clearTokenRefresh()
            },
            restartAppSuccess: () => {
                actions.startPolling()
                actions.clearTokenRefresh()
            },
        }
    }),

    afterMount(({ actions }) => {
        actions.loadStreamlitApp()
    }),

    beforeUnmount(({ actions }) => {
        actions.stopPolling()
        actions.stopHealthPolling()
        actions.clearTokenRefresh()
    }),
])
