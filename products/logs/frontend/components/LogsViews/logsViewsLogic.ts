import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { LogsViewApi, LogsViewApiFilters } from 'products/logs/frontend/generated/api.schemas'
import { DEFAULT_ACTIVE_TAB, logsSceneLogic } from 'products/logs/frontend/logsSceneLogic'

import type { logsViewsLogicType } from './logsViewsLogicType'

export type LogsView = LogsViewApi

export interface LogsViewsLogicProps {
    id: string
}

const logsViewsUrl = (teamId: number | null): string => `api/environments/${teamId}/logs/views`

export const logsViewsLogic = kea<logsViewsLogicType>([
    props({} as LogsViewsLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsViews', 'logsViewsLogic', key]),

    connect((props: LogsViewsLogicProps) => ({
        values: [teamLogic, ['currentTeamId']],
        actions: [
            logsViewerFiltersLogic({ id: props.id }),
            ['setFilters'],
            logsSceneLogic({ tabId: props.id }),
            ['setActiveTab'],
        ],
    })),

    actions({
        deleteView: (shortId: string) => ({ shortId }),
        loadView: (view: LogsView) => ({ view }),
    }),

    loaders(({ values }) => ({
        views: [
            [] as LogsView[],
            {
                loadViews: async () => {
                    const response = await api.get(`${logsViewsUrl(values.currentTeamId)}/`)
                    return response.results
                },
                createView: async ({ name, filters }: { name: string; filters: LogsViewApiFilters }) => {
                    const created: LogsView = await api.create(`${logsViewsUrl(values.currentTeamId)}/`, {
                        name,
                        filters,
                    })
                    lemonToast.success('View saved')
                    return [created, ...values.views]
                },
            },
        ],
    })),

    reducers({
        views: {
            deleteView: (state, { shortId }) => state.filter((v) => v.short_id !== shortId),
        },
    }),

    listeners(({ actions, values }) => ({
        deleteView: async ({ shortId }) => {
            try {
                await api.delete(`${logsViewsUrl(values.currentTeamId)}/${shortId}/`)
                lemonToast.success('View deleted')
            } catch {
                lemonToast.error('Failed to delete view')
                actions.loadViews()
            }
        },
        loadView: ({ view }) => {
            actions.setFilters(view.filters || {})
            actions.setActiveTab(DEFAULT_ACTIVE_TAB)
        },
        createViewFailure: () => {
            lemonToast.error('Failed to save view')
        },
        loadViewsFailure: () => {
            lemonToast.error('Failed to load saved views')
        },
    })),
])
