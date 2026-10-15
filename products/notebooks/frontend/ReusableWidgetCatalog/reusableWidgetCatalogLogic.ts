import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { PaginationManual } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { reusableWidgetsList } from 'products/notebooks/frontend/generated/api'
import type { ReusableWidgetPageApi, ReusableWidgetSummaryApi } from 'products/notebooks/frontend/generated/api.schemas'

const RESULTS_PER_PAGE = 50

export interface reusableWidgetCatalogLogicValues {
    currentTeamId: number | null
    page: number
    pagination: PaginationManual
    reusableWidgets: ReusableWidgetSummaryApi[]
    reusableWidgetsError: string | null
    reusableWidgetsResponse: ReusableWidgetPageApi | null
    reusableWidgetsResponseLoading: boolean
    search: string
}

export interface reusableWidgetCatalogLogicActions {
    loadReusableWidgets: () => { value: true }
    loadReusableWidgetsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadReusableWidgetsSuccess: (
        reusableWidgetsResponse: ReusableWidgetPageApi,
        payload?: { value: true }
    ) => { reusableWidgetsResponse: ReusableWidgetPageApi; payload?: { value: true } }
    setPage: (page: number) => { page: number }
    setSearch: (search: string) => { search: string }
}

export interface reusableWidgetCatalogLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        pagination: (page: number, response: ReusableWidgetPageApi | null) => PaginationManual
        reusableWidgets: (response: ReusableWidgetPageApi | null) => ReusableWidgetSummaryApi[]
    }
}

export type reusableWidgetCatalogLogicType = MakeLogicType<
    reusableWidgetCatalogLogicValues,
    reusableWidgetCatalogLogicActions,
    Record<string, never>,
    reusableWidgetCatalogLogicMeta
>

export const reusableWidgetCatalogLogic = kea<reusableWidgetCatalogLogicType>([
    path(['products', 'notebooks', 'ReusableWidgetCatalog', 'reusableWidgetCatalogLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        setPage: (page: number) => ({ page }),
        setSearch: (search: string) => ({ search }),
    }),
    reducers({
        page: [1, { setPage: (_, { page }) => page, setSearch: () => 1 }],
        search: ['', { setSearch: (_, { search }) => search }],
        reusableWidgetsError: [
            null as string | null,
            {
                loadReusableWidgets: () => null,
                loadReusableWidgetsSuccess: () => null,
                loadReusableWidgetsFailure: (_, { error }) => error,
            },
        ],
    }),
    loaders(({ values }) => ({
        reusableWidgetsResponse: [
            null as ReusableWidgetPageApi | null,
            {
                loadReusableWidgets: async (_, breakpoint) => {
                    await breakpoint(250)
                    if (!values.currentTeamId) {
                        return { results: [], count: 0, next_offset: null }
                    }
                    const response = await reusableWidgetsList(String(values.currentTeamId), {
                        search: values.search || undefined,
                        offset: (values.page - 1) * RESULTS_PER_PAGE,
                        limit: RESULTS_PER_PAGE,
                    })
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setPage: actions.loadReusableWidgets,
        setSearch: actions.loadReusableWidgets,
    })),
    selectors(({ actions }) => ({
        reusableWidgets: [
            (selectors) => [selectors.reusableWidgetsResponse],
            (response): ReusableWidgetSummaryApi[] => response?.results ?? [],
        ],
        pagination: [
            (selectors) => [selectors.page, selectors.reusableWidgetsResponse],
            (page, response): PaginationManual => ({
                controlled: true,
                pageSize: RESULTS_PER_PAGE,
                currentPage: page,
                entryCount: response?.count ?? 0,
                onBackward: () => actions.setPage(page - 1),
                onForward: () => actions.setPage(page + 1),
            }),
        ],
    })),
])
