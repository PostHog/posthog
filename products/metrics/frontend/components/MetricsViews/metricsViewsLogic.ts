import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { metricsViewsCreate, metricsViewsDestroy, metricsViewsList } from 'products/metrics/frontend/generated/api'
import type { MetricsViewApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsViewerLogic } from '../metricsViewerLogic'
import type { MetricsViewerSavedFilters } from '../metricsViewerState'
import type { metricsViewsLogicType } from './metricsViewsLogicType'

export const metricsViewsLogic = kea<metricsViewsLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'MetricsViews', 'metricsViewsLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
        actions: [metricsViewerLogic, ['applySavedState']],
    })),

    actions({
        deleteView: (shortId: string) => ({ shortId }),
        loadView: (view: MetricsViewApi) => ({ view }),
    }),

    loaders(({ values }) => ({
        views: [
            [] as MetricsViewApi[],
            {
                loadViews: async () => {
                    const response = await metricsViewsList(String(values.currentTeamId))
                    return response.results
                },
                createView: async ({ name, filters }: { name: string; filters: MetricsViewerSavedFilters }) => {
                    const created = await metricsViewsCreate(String(values.currentTeamId), { name, filters })
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
                await metricsViewsDestroy(String(values.currentTeamId), shortId)
                lemonToast.success('View deleted')
            } catch {
                lemonToast.error('Failed to delete view')
                actions.loadViews()
            }
        },
        loadView: ({ view }) => {
            actions.applySavedState((view.filters ?? {}) as MetricsViewerSavedFilters)
        },
        createViewFailure: () => {
            lemonToast.error('Failed to save view')
        },
        loadViewsFailure: () => {
            lemonToast.error('Failed to load saved views')
        },
    })),
])
