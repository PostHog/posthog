import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { streamlitAppLogicType } from './streamlitAppLogicType'
import { StreamlitAppConnectUrl, StreamlitAppSandbox, StreamlitAppStatus, StreamlitAppType } from './types'

export interface StreamlitAppLogicProps {
    shortId: string
}

const POLL_INTERVAL_MS = 2000
const TOKEN_REFRESH_INTERVAL_MS = 4 * 60 * 1000 // 4 minutes

export const streamlitAppLogic = kea<streamlitAppLogicType>([
    path(['products', 'streamlit_apps', 'frontend', 'streamlitAppLogic']),
    props({} as StreamlitAppLogicProps),
    key((props) => props.shortId),

    actions({
        startPolling: true,
        stopPolling: true,
        startTokenRefresh: true,
        stopTokenRefresh: true,
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
        connectUrl: [
            null as StreamlitAppConnectUrl | null,
            {
                loadConnectUrl: async () => {
                    return await api.streamlitApps.connectUrl(props.shortId)
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
        isRefreshingToken: [
            false,
            {
                startTokenRefresh: () => true,
                stopTokenRefresh: () => false,
            },
        ],
    }),

    selectors({
        appStatus: [
            (s) => [s.sandboxStatus],
            (sandboxStatus): StreamlitAppStatus => sandboxStatus?.status ?? 'stopped',
        ],
        iframeSrc: [
            (s) => [s.connectUrl],
            (connectUrl): string | null => {
                if (!connectUrl) {
                    return null
                }
                return `${connectUrl.url}?_modal_connect_token=${connectUrl.token}`
            },
        ],
    }),

    listeners(({ actions, cache }) => ({
        loadStreamlitAppSuccess: ({ streamlitApp }) => {
            if (!streamlitApp) {
                return
            }
            // Auto-start if the app is stopped
            const status = streamlitApp.sandbox?.status ?? 'stopped'
            if (status === 'stopped' && streamlitApp.active_version) {
                actions.startApp()
            } else if (status === 'starting') {
                actions.startPolling()
            } else if (status === 'running') {
                actions.loadConnectUrl()
            }
        },
        startAppSuccess: () => {
            actions.startPolling()
        },
        startPolling: () => {
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
        loadSandboxStatusSuccess: ({ sandboxStatus }) => {
            if (!sandboxStatus) {
                return
            }
            if (sandboxStatus.status === 'running') {
                actions.stopPolling()
                actions.loadConnectUrl()
            } else if (sandboxStatus.status === 'error' || sandboxStatus.status === 'stopped') {
                actions.stopPolling()
            }
        },
        loadConnectUrlSuccess: ({ connectUrl }) => {
            if (connectUrl) {
                actions.startTokenRefresh()
            }
        },
        startTokenRefresh: () => {
            cache.tokenTimer = setInterval(() => {
                actions.loadConnectUrl()
            }, TOKEN_REFRESH_INTERVAL_MS)
        },
        stopTokenRefresh: () => {
            if (cache.tokenTimer) {
                clearInterval(cache.tokenTimer)
                cache.tokenTimer = null
            }
        },
        stopAppSuccess: () => {
            actions.stopPolling()
            actions.stopTokenRefresh()
        },
        restartAppSuccess: () => {
            actions.stopTokenRefresh()
            actions.startPolling()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadStreamlitApp()
    }),

    beforeUnmount(({ actions }) => {
        actions.stopPolling()
        actions.stopTokenRefresh()
    }),
])
