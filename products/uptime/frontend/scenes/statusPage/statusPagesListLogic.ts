import { actions, afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { statusPagesListLogicType } from './statusPagesListLogicType'

export interface StatusPageListItem {
    id: string
    title: string
    slug: string
    monitor_ids: string[]
    is_published: boolean
    published_at: string | null
    created_at: string
    updated_at: string
}

export const statusPagesListLogic = kea<statusPagesListLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'statusPage', 'statusPagesListLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        createNewStatusPage: true,
        deleteStatusPage: (id: string) => ({ id }),
    }),

    loaders(({ values }) => ({
        statusPages: [
            [] as StatusPageListItem[],
            {
                loadStatusPages: async () => {
                    return await api.get<StatusPageListItem[]>(
                        `api/projects/${values.currentProjectId}/uptime/status_pages/`
                    )
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        createNewStatusPage: async () => {
            const created = await api.create<StatusPageListItem>(
                `api/projects/${values.currentProjectId}/uptime/status_pages/`,
                {}
            )
            router.actions.push(`/uptime/status-pages/${created.id}`)
        },
        deleteStatusPage: async ({ id }) => {
            await api.delete(`api/projects/${values.currentProjectId}/uptime/status_pages/${id}/`)
            lemonToast.info('Status page deleted')
            actions.loadStatusPages()
        },
    })),

    urlToAction(({ actions }) => ({
        '/uptime': () => {
            // Re-fetch when the user navigates back to the Uptime page so edits/deletes are reflected.
            actions.loadStatusPages()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadStatusPages()
    }),
])
