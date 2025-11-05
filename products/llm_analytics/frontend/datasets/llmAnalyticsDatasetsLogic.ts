import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api, { CountedPaginatedResponse } from '~/lib/api'
import { Sorting } from '~/lib/lemon-ui/LemonTable'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { objectsEqual } from '~/lib/utils'
import { sceneLogic } from '~/scenes/sceneLogic'
import { urls } from '~/scenes/urls'
import { Dataset } from '~/types'

import type { llmAnalyticsDatasetsLogicType } from './llmAnalyticsDatasetsLogicType'

export const DATASETS_PER_PAGE = 30

export interface DatasetFilters {
    page: number
    search: string
    order_by: string
}

function cleanFilters(values: Partial<DatasetFilters>): DatasetFilters {
    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        order_by: values.order_by || '-created_at',
    }
}

export const llmAnalyticsDatasetsLogic = kea<llmAnalyticsDatasetsLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsDatasetsLogic']),

    actions({
        setFilters: (filters: Partial<DatasetFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadDatasets: (debounce: boolean = true) => ({ debounce }),
        deleteDataset: (datasetId: string) => ({ datasetId }),
    }),

    reducers({
        rawFilters: [
            null as Partial<DatasetFilters> | null,
            {
                setFilters: (state, { filters, merge }) =>
                    cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        // Reset page on filter change except if it's page that's being updated
                        ...('page' in filters ? {} : { page: 1 }),
                    }),
            },
        ],
    }),

    loaders(({ values }) => ({
        datasets: [
            { results: [], count: 0, offset: 0 } as CountedPaginatedResponse<Dataset>,
            {
                loadDatasets: async ({ debounce }, breakpoint) => {
                    if (debounce && values.datasets.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { filters } = values
                    const params = {
                        search: filters.search,
                        order_by: filters.order_by,
                        offset: Math.max(0, (filters.page - 1) * DATASETS_PER_PAGE),
                        limit: DATASETS_PER_PAGE,
                    }

                    // Scroll to top if the page changed, except if changed via back/forward
                    if (
                        sceneLogic.findMounted()?.values.activeSceneId === 'LLMAnalyticsDatasets' &&
                        router.values.lastMethod !== 'POP' &&
                        values.datasets.results.length > 0 &&
                        values.rawFilters?.page !== filters.page
                    ) {
                        window.scrollTo(0, 0)
                    }

                    const response = await api.datasets.list(params)
                    return response
                },
            },
        ],
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<DatasetFilters> | null): DatasetFilters => cleanFilters(rawFilters || {}),
        ],

        count: [(s) => [s.datasets], (datasets: CountedPaginatedResponse<Dataset>) => datasets.count],

        sorting: [
            (s) => [s.filters],
            (filters: DatasetFilters): Sorting | null => {
                if (!filters.order_by) {
                    return {
                        columnKey: 'updated_at',
                        order: -1,
                    }
                }
                return filters.order_by.startsWith('-')
                    ? {
                          columnKey: filters.order_by.slice(1),
                          order: -1,
                      }
                    : {
                          columnKey: filters.order_by,
                          order: 1,
                      }
            },
        ],

        pagination: [
            (s) => [s.filters, s.count],
            (filters: DatasetFilters, count: number): PaginationManual => ({
                controlled: true,
                pageSize: DATASETS_PER_PAGE,
                currentPage: filters.page,
                entryCount: count,
            }),
        ],

        datasetCountLabel: [
            (s) => [s.filters, s.count],
            (filters, count) => {
                const start = (filters.page - 1) * DATASETS_PER_PAGE + 1
                const end = Math.min(filters.page * DATASETS_PER_PAGE, count)

                return count === 0 ? '0 datasets' : `${start}-${end} of ${count} dataset${count === 1 ? '' : 's'}`
            },
        ],
    }),

    listeners(({ asyncActions, values, selectors }) => ({
        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const { filters } = values

            if (!objectsEqual(oldFilters, filters)) {
                await asyncActions.loadDatasets(debounce)
            }
        },

        deleteDataset: async ({ datasetId }) => {
            try {
                const datasetName = values.datasets.results.find((dataset) => dataset.id === datasetId)?.name
                await api.datasets.update(datasetId, { deleted: true })
                lemonToast.info(`${datasetName || 'Dataset'} has been deleted.`)
                await asyncActions.loadDatasets(false)
            } catch {
                lemonToast.error('Failed to delete dataset')
            }
        },
    })),

    actionToUrl(({ values }) => {
        const changeUrl = ():
            | [
                  string,
                  Record<string, any>,
                  Record<string, any>,
                  {
                      replace: boolean
                  },
              ]
            | void => {
            const nextValues = cleanFilters(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)
            if (!objectsEqual(nextValues, urlValues)) {
                return [urls.llmAnalyticsDatasets(), nextValues, {}, { replace: false }]
            }
        }
        return {
            setFilters: changeUrl,
        }
    }),

    urlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsDatasets()]: (_, searchParams) => {
            const newFilters = cleanFilters(searchParams)
            if (values.rawFilters === null || !objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadDatasets()
    }),
])
