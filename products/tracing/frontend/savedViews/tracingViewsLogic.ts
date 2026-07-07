import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { TRACING_SCENE_VIEWER_ID, TracingFilters, tracingFiltersLogic } from '../tracingFiltersLogic'
import type { tracingViewsLogicType } from './tracingViewsLogicType'

// Subset of TracingFilters persisted in a saved view. Compare-mode and the dragged overlay windows
// are ephemeral UI state tied to on-screen sparkline data, so they're intentionally excluded.
export type SavedTracingFilters = Pick<
    TracingFilters,
    'dateRange' | 'serviceNames' | 'filterGroup' | 'orderBy' | 'orderDirection' | 'viewMode'
>

// Handwritten until `hogli build:openapi` generates `TracingViewApi` from TracingViewSerializer.
export interface TracingView {
    id: string
    short_id: string
    name: string
    filters: Partial<SavedTracingFilters>
    pinned: boolean
    created_at: string
    created_by: {
        first_name?: string
        email?: string
    } | null
    updated_at: string | null
}

const tracingViewsUrl = (teamId: number | null): string => `api/projects/${teamId}/tracing/views`

export const tracingViewsLogic = kea<tracingViewsLogicType>([
    path(['products', 'tracing', 'frontend', 'savedViews', 'tracingViewsLogic']),

    // Saved views are a /tracing scene feature — always bind the scene's viewer instance.
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
        actions: [tracingFiltersLogic({ id: TRACING_SCENE_VIEWER_ID }), ['setFilters']],
    })),

    actions({
        deleteView: (shortId: string) => ({ shortId }),
        loadView: (view: TracingView) => ({ view }),
    }),

    loaders(({ values }) => ({
        views: [
            [] as TracingView[],
            {
                loadViews: async () => {
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get(`${tracingViewsUrl(values.currentTeamId)}/`)
                    return response.results
                },
                createView: async ({ name, filters }: { name: string; filters: Partial<SavedTracingFilters> }) => {
                    // nosemgrep: prefer-codegen-api
                    const created: TracingView = await api.create(`${tracingViewsUrl(values.currentTeamId)}/`, {
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
                // nosemgrep: prefer-codegen-api
                await api.delete(`${tracingViewsUrl(values.currentTeamId)}/${shortId}/`)
                lemonToast.success('View deleted')
            } catch {
                lemonToast.error('Failed to delete view')
                actions.loadViews()
            }
        },
        loadView: ({ view }) => {
            actions.setFilters(view.filters || {})
        },
        createViewFailure: () => {
            lemonToast.error('Failed to save view')
        },
        loadViewsFailure: () => {
            lemonToast.error('Failed to load saved views')
        },
    })),
])
