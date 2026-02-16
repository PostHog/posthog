import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { streamlitAppLogicType } from './streamlitAppLogicType'
import { StreamlitAppSandbox, StreamlitAppStatus, StreamlitAppType } from './types'

export interface StreamlitAppLogicProps {
    shortId: string
}

const POLL_INTERVAL_MS = 2000
const HEALTH_POLL_INTERVAL_MS = 15000

export const streamlitAppLogic = kea<streamlitAppLogicType>([
    path(['products', 'streamlit_apps', 'frontend', 'streamlitAppLogic']),
    props({} as StreamlitAppLogicProps),
    key((props) => props.shortId),

    actions({
        startPolling: true,
        stopPolling: true,
        startHealthPolling: true,
        stopHealthPolling: true,
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
            (s) => [s.appStatus, s.streamlitApp],
            (appStatus, streamlitApp): string | null => {
                if (appStatus !== 'running' || !streamlitApp) {
                    return null
                }
                const teamId = teamLogic.findMounted()?.values.currentTeamId
                if (!teamId) {
                    return null
                }
                return `/api/projects/${teamId}/streamlit_apps/${streamlitApp.short_id}/proxy/`
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
            if (status === 'stopped' && streamlitApp.active_version) {
                actions.startApp()
            } else if (status === 'starting') {
                actions.startPolling()
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
        startHealthPolling: () => {
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
            } else if (sandboxStatus.status === 'error' || sandboxStatus.status === 'stopped') {
                actions.stopPolling()
                actions.stopHealthPolling()
            }
        },
        stopAppSuccess: () => {
            actions.stopPolling()
            actions.stopHealthPolling()
        },
        restartAppSuccess: () => {
            actions.startPolling()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadStreamlitApp()
    }),

    beforeUnmount(({ actions }) => {
        actions.stopPolling()
        actions.stopHealthPolling()
    }),
])
