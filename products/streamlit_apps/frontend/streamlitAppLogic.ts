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
// Clamp the refresh delay so a tiny expires_in (or NaN from a malformed
// response) can't schedule an immediate-loop refresh that DDoSes our own API.
const MIN_TOKEN_REFRESH_MS = 5_000

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
            // Restart kicks off a new sandbox, so the previous iframe URL +
            // tokens are stale. Clearing forces the running-state branch to
            // refetch a fresh connect URL once the new sandbox is up.
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

    listeners(({ actions, values, cache }) => ({
        loadStreamlitAppSuccess: ({ streamlitApp }) => {
            if (!streamlitApp) {
                return
            }
            // Seed sandboxStatus from app data so appStatus is correct immediately
            if (streamlitApp.sandbox) {
                actions.loadSandboxStatusSuccess({ sandboxStatus: streamlitApp.sandbox })
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
            // Clear any existing timer first — kea listeners can fire multiple
            // times (status changes, reloads) and setInterval would stack
            // without this guard, leading to runaway API calls.
            if (cache.pollTimer) {
                clearInterval(cache.pollTimer)
            }
            cache.pollTimer = setInterval(() => {
                actions.loadSandboxStatus()
            }, POLL_INTERVAL_MS)
        },
        stopPolling: () => {
            if (cache.pollTimer) {
                clearInterval(cache.pollTimer)
                cache.pollTimer = null
            }
        },
        startHealthPolling: () => {
            if (cache.healthPollTimer) {
                clearInterval(cache.healthPollTimer)
            }
            cache.healthPollTimer = setInterval(() => {
                actions.loadSandboxStatus()
            }, HEALTH_POLL_INTERVAL_MS)
        },
        stopHealthPolling: () => {
            if (cache.healthPollTimer) {
                clearInterval(cache.healthPollTimer)
                cache.healthPollTimer = null
            }
        },
        loadSandboxStatusSuccess: ({ sandboxStatus }) => {
            if (!sandboxStatus) {
                return
            }
            if (sandboxStatus.status === 'running') {
                actions.stopPolling()
                if (!values.isHealthPolling) {
                    actions.startHealthPolling()
                }
                // Fetch connect info when sandbox becomes running
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
            // Don't reschedule on failure — that would create a 5-second retry
            // loop that hammers the server while the sandbox is broken. The
            // user can hit Retry from the connect-error UI branch.
            actions.clearTokenRefresh()
        },
        clearTokenRefresh: () => {
            if (cache.tokenRefreshTimer) {
                clearTimeout(cache.tokenRefreshTimer)
                cache.tokenRefreshTimer = null
            }
        },
        stopAppSuccess: () => {
            actions.stopPolling()
            actions.stopHealthPolling()
            actions.clearTokenRefresh()
        },
        restartAppSuccess: () => {
            actions.startPolling()
            actions.clearTokenRefresh()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadStreamlitApp()
    }),

    beforeUnmount(({ actions }) => {
        actions.stopPolling()
        actions.stopHealthPolling()
        actions.clearTokenRefresh()
    }),
])
