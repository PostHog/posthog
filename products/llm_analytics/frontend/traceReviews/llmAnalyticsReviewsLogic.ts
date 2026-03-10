import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { Sorting } from 'lib/lemon-ui/LemonTable'

import { CountedPaginatedResponse } from '~/lib/api'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { tabAwareActionToUrl } from '~/lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from '~/lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual, pluralize } from '~/lib/utils'
import { urls } from '~/scenes/urls'

import { cleanPagedSearchOrderParams } from '../utils'
import type { llmAnalyticsReviewsLogicType } from './llmAnalyticsReviewsLogicType'
import { traceReviewsApi } from './traceReviewsApi'
import type { TraceReview } from './types'

export const TRACE_REVIEWS_PER_PAGE = 30

export interface TraceReviewFilters {
    page: number
    search: string
    order_by: string
}

function cleanFilters(values: Partial<TraceReviewFilters>): TraceReviewFilters {
    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        order_by: values.order_by || '-updated_at',
    }
}

export interface LLMAnalyticsReviewsLogicProps {
    tabId?: string
}

export const llmAnalyticsReviewsLogic = kea<llmAnalyticsReviewsLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsReviewsLogic']),
    props({} as LLMAnalyticsReviewsLogicProps),
    key((props: LLMAnalyticsReviewsLogicProps) => props.tabId ?? 'default'),

    actions({
        setFilters: (filters: Partial<TraceReviewFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadReviews: (debounce: boolean = true) => ({ debounce }),
    }),

    reducers({
        rawFilters: [
            null as Partial<TraceReviewFilters> | null,
            {
                setFilters: (state, { filters, merge }) =>
                    cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        ...('page' in filters ? {} : { page: 1 }),
                    }),
            },
        ],
    }),

    loaders(({ values }) => ({
        reviews: [
            { results: [], count: 0, offset: 0 } as CountedPaginatedResponse<TraceReview>,
            {
                loadReviews: async ({ debounce }, breakpoint) => {
                    if (debounce && values.reviews.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { filters } = values

                    return traceReviewsApi.list({
                        search: filters.search,
                        order_by: filters.order_by,
                        offset: Math.max(0, (filters.page - 1) * TRACE_REVIEWS_PER_PAGE),
                        limit: TRACE_REVIEWS_PER_PAGE,
                    })
                },
            },
        ],
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<TraceReviewFilters> | null): TraceReviewFilters => cleanFilters(rawFilters || {}),
        ],

        count: [(s) => [s.reviews], (reviews: CountedPaginatedResponse<TraceReview>) => reviews.count],

        sorting: [
            (s) => [s.filters],
            (filters: TraceReviewFilters): Sorting | null => {
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
            (filters: TraceReviewFilters, count: number): PaginationManual => ({
                controlled: true,
                pageSize: TRACE_REVIEWS_PER_PAGE,
                currentPage: filters.page,
                entryCount: count,
            }),
        ],

        reviewCountLabel: [
            (s) => [s.filters, s.count],
            (filters: TraceReviewFilters, count: number): string => {
                const start = (filters.page - 1) * TRACE_REVIEWS_PER_PAGE + 1
                const end = Math.min(filters.page * TRACE_REVIEWS_PER_PAGE, count)

                return count === 0 ? '0 reviews' : `${start}-${end} of ${pluralize(count, 'review')}`
            },
        ],
    }),

    listeners(({ asyncActions, values, selectors }) => ({
        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)

            if (!objectsEqual(oldFilters, values.filters)) {
                await asyncActions.loadReviews(debounce)
            }
        },
    })),

    tabAwareActionToUrl(({ values }) => {
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
            const nextValues = cleanPagedSearchOrderParams(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)

            if (!objectsEqual(values.filters, urlValues)) {
                return [urls.llmAnalyticsReviews(), nextValues, {}, { replace: true }]
            }
        }

        return {
            setFilters: changeUrl,
        }
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsReviews()]: (_, searchParams, __, { method }) => {
            const newFilters = cleanFilters(searchParams)

            if (!objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            } else if (method !== 'REPLACE') {
                actions.loadReviews(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadReviews()
    }),
])
