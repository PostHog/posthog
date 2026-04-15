import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import type { streamlitAppsLogicType } from './streamlitAppsLogicType'
import { StreamlitAppMinimalType, StreamlitAppType } from './types'

const LIST_POLL_INTERVAL_MS = 10_000

export const streamlitAppsLogic = kea<streamlitAppsLogicType>([
    path(['products', 'streamlit_apps', 'frontend', 'streamlitAppsLogic']),

    actions({
        updateStreamlitApp: (app: StreamlitAppType | StreamlitAppMinimalType) => ({ app }),
        startListPolling: true,
        stopListPolling: true,
    }),

    loaders(({ values }) => ({
        streamlitApps: [
            [] as StreamlitAppMinimalType[],
            {
                loadStreamlitApps: async () => {
                    const response = await api.streamlitApps.list()
                    return response.results
                },
                createStreamlitApp: async ({ name, description }: { name: string; description?: string }) => {
                    const newApp = await api.streamlitApps.create({ name, description })
                    lemonToast.success('App created')
                    router.actions.push(urls.streamlitAppEdit(newApp.short_id))
                    return [...values.streamlitApps, newApp as StreamlitAppMinimalType]
                },
                deleteStreamlitApp: async ({ shortId }: { shortId: string }) => {
                    await api.streamlitApps.delete(shortId)
                    lemonToast.success('App deleted')
                    return values.streamlitApps.filter((a) => a.short_id !== shortId)
                },
            },
        ],
    })),

    reducers({
        streamlitApps: {
            updateStreamlitApp: (state, { app }) =>
                state.map((a) => (a.short_id === app.short_id ? { ...a, ...app } : a)),
        },
    }),

    listeners(({ actions, cache }) => ({
        startListPolling: () => {
            // Idempotent — timers stack otherwise on re-fire.
            if (cache.listPollTimer) {
                clearInterval(cache.listPollTimer)
            }
            cache.listPollTimer = setInterval(() => {
                if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
                    return
                }
                actions.loadStreamlitApps()
            }, LIST_POLL_INTERVAL_MS)
        },
        stopListPolling: () => {
            if (cache.listPollTimer) {
                clearInterval(cache.listPollTimer)
                cache.listPollTimer = null
            }
        },
    })),

    afterMount(({ actions, cache }) => {
        actions.loadStreamlitApps()
        actions.startListPolling()
        // Refetch immediately when the tab becomes visible again so a user
        // returning to the page doesn't see stale state for up to 10s.
        if (typeof document !== 'undefined') {
            cache.visibilityHandler = (): void => {
                if (document.visibilityState === 'visible') {
                    actions.loadStreamlitApps()
                }
            }
            document.addEventListener('visibilitychange', cache.visibilityHandler)
        }
    }),

    beforeUnmount(({ actions, cache }) => {
        actions.stopListPolling()
        if (typeof document !== 'undefined' && cache.visibilityHandler) {
            document.removeEventListener('visibilitychange', cache.visibilityHandler)
            cache.visibilityHandler = null
        }
    }),
])
