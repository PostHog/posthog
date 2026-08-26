import { LogicWrapper, MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { notebookWidgetsList } from 'products/notebooks/frontend/generated/api'
import type { WidgetCatalogApi } from 'products/notebooks/frontend/generated/api.schemas'

const PAGE_SIZE = 50

export interface generatedWidgetsLogicValues {
    count: number
    currentTeamId: number | null
    error: string | null
    loading: boolean
    nextOffset: number | null
    search: string
    widgets: WidgetCatalogApi[]
}

export interface generatedWidgetsLogicActions {
    loadMore: () => { value: true }
    loadWidgets: (reset: boolean) => { reset: boolean }
    loadWidgetsFailed: (error: string) => { error: string }
    loadWidgetsSuccess: (
        widgets: WidgetCatalogApi[],
        count: number,
        nextOffset: number | null,
        reset: boolean
    ) => { widgets: WidgetCatalogApi[]; count: number; nextOffset: number | null; reset: boolean }
    setSearch: (search: string) => { search: string }
}

export interface generatedWidgetsLogicMeta {
    key: string
}

export type generatedWidgetsLogicType = MakeLogicType<
    generatedWidgetsLogicValues,
    generatedWidgetsLogicActions,
    Record<string, never>,
    generatedWidgetsLogicMeta
>

export const generatedWidgetsLogic: LogicWrapper<generatedWidgetsLogicType> = kea<generatedWidgetsLogicType>([
    path(['products', 'notebooks', 'generatedWidgetsLogic']),
    connect({ values: [teamLogic, ['currentTeamId']] }),
    actions({
        loadMore: true,
        loadWidgets: (reset: boolean) => ({ reset }),
        loadWidgetsFailed: (error: string) => ({ error }),
        loadWidgetsSuccess: (
            widgets: WidgetCatalogApi[],
            count: number,
            nextOffset: number | null,
            reset: boolean
        ) => ({ widgets, count, nextOffset, reset }),
        setSearch: (search: string) => ({ search }),
    }),
    reducers({
        count: [0, { loadWidgetsSuccess: (_, { count }) => count }],
        error: [
            null as string | null,
            {
                loadWidgets: () => null,
                loadWidgetsFailed: (_, { error }) => error,
            },
        ],
        loading: [
            false,
            {
                loadWidgets: () => true,
                loadWidgetsFailed: () => false,
                loadWidgetsSuccess: () => false,
            },
        ],
        nextOffset: [
            null as number | null,
            {
                loadWidgetsSuccess: (_, { nextOffset }) => nextOffset,
            },
        ],
        search: ['', { setSearch: (_, { search }) => search }],
        widgets: [
            [] as WidgetCatalogApi[],
            {
                loadWidgetsSuccess: (current, { widgets, reset }) => (reset ? widgets : [...current, ...widgets]),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadMore: () => {
            if (values.nextOffset !== null) {
                actions.loadWidgets(false)
            }
        },
        loadWidgets: async ({ reset }, breakpoint) => {
            if (!values.currentTeamId) {
                actions.loadWidgetsSuccess([], 0, null, true)
                return
            }
            const offset = reset ? 0 : (values.nextOffset ?? values.widgets.length)
            try {
                const page = await notebookWidgetsList(String(values.currentTeamId), {
                    limit: PAGE_SIZE,
                    offset,
                    search: values.search || undefined,
                })
                breakpoint()
                actions.loadWidgetsSuccess(
                    page.results,
                    page.count,
                    page.next ? offset + page.results.length : null,
                    reset
                )
            } catch (error) {
                breakpoint()
                actions.loadWidgetsFailed(error instanceof Error ? error.message : 'The widgets could not be loaded.')
            }
        },
        setSearch: async (_, breakpoint) => {
            await breakpoint(250)
            actions.loadWidgets(true)
        },
    })),
    afterMount(({ actions }) => actions.loadWidgets(true)),
])
