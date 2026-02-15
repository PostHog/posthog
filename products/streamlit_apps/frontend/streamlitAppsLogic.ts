import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import type { streamlitAppsLogicType } from './streamlitAppsLogicType'
import { StreamlitAppMinimalType, StreamlitAppType } from './types'

export const streamlitAppsLogic = kea<streamlitAppsLogicType>([
    path(['products', 'streamlit_apps', 'frontend', 'streamlitAppsLogic']),

    actions({
        updateStreamlitApp: (app: StreamlitAppType | StreamlitAppMinimalType) => ({ app }),
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

    listeners(() => ({})),

    afterMount(({ actions }) => {
        actions.loadStreamlitApps()
    }),
])
