import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { Sorting } from 'lib/lemon-ui/LemonTable'

import { CountedPaginatedResponse } from '~/lib/api'
import { ApiConfig } from '~/lib/api'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { tabAwareActionToUrl } from '~/lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from '~/lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual, pluralize } from '~/lib/utils'
import { urls } from '~/scenes/urls'

import { llmAnalyticsScoreDefinitionsList } from '../generated/api'
import type { ScoreDefinitionApi } from '../generated/api.schemas'
import type { llmAnalyticsReviewsLogicType } from './llmAnalyticsReviewsLogicType'
import { traceReviewsApi } from './traceReviewsApi'
import type { TraceReview } from './types'

export const TRACE_REVIEWS_PER_PAGE = 30

export interface TraceReviewFilters {
    page: number
    search: string
    definition_id: string
    order_by: string
}

const ALLOWED_ORDER_BY_VALUES = new Set(['updated_at', '-updated_at', 'created_at', '-created_at'])

function cleanFilters(values: Record<string, unknown>): TraceReviewFilters {
    const pageValue = values.page ?? values.review_page
    const searchValue = values.search ?? values.review_search
    const definitionValue = values.definition_id ?? values.review_definition_id
    const orderByValue = values.order_by ?? values.review_order_by
    const orderBy =
        typeof orderByValue === 'string' && ALLOWED_ORDER_BY_VALUES.has(orderByValue) ? orderByValue : '-updated_at'

    return {
        page: parseInt(String(pageValue)) || 1,
        search: String(searchValue || ''),
        definition_id: typeof definitionValue === 'string' ? definitionValue : '',
        order_by: orderBy,
    }
}

function getUrlFilters(filters: TraceReviewFilters): Record<string, unknown> {
    return {
        review_page: filters.page === 1 ? undefined : filters.page,
        review_search: filters.search || undefined,
        review_definition_id: filters.definition_id || undefined,
        review_order_by: filters.order_by === '-updated_at' ? undefined : filters.order_by,
    }
}

export interface LLMAnalyticsReviewsLogicProps {
    tabId?: string
}

export const llmAnalyticsReviewsLogic = kea<llmAnalyticsReviewsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'traceReviews', 'llmAnalyticsReviewsLogic']),
    props({} as LLMAnalyticsReviewsLogicProps),
    key((props: LLMAnalyticsReviewsLogicProps) => props.tabId ?? 'default'),

    actions({
        setFilters: (filters: Partial<TraceReviewFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadReviews: (debounce: boolean = true) => ({ debounce }),
        loadScoreDefinitionOptions: true,
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
                        search: filters.search || undefined,
                        definition_id: filters.definition_id || undefined,
                        order_by: filters.order_by,
                        offset: Math.max(0, (filters.page - 1) * TRACE_REVIEWS_PER_PAGE),
                        limit: TRACE_REVIEWS_PER_PAGE,
                    })
                },
            },
        ],

        scoreDefinitionOptions: [
            [] as ScoreDefinitionApi[],
            {
                loadScoreDefinitionOptions: async () => {
                    const response = await llmAnalyticsScoreDefinitionsList(String(ApiConfig.getCurrentTeamId()), {
                        archived: false,
                        order_by: 'name',
                        limit: 1000,
                    })

                    return response.results
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
            (filters: TraceReviewFilters): Sorting | null =>
                filters.order_by.startsWith('-')
                    ? { columnKey: filters.order_by.slice(1), order: -1 }
                    : { columnKey: filters.order_by, order: 1 },
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

    tabAwareActionToUrl(({ values }) => ({
        setFilters: () => {
            const nextValues = { ...getUrlFilters(values.filters), human_reviews_tab: 'reviews' }
            const urlValues = {
                ...getUrlFilters(cleanFilters(router.values.searchParams)),
                human_reviews_tab: router.values.searchParams.human_reviews_tab === 'reviews' ? 'reviews' : undefined,
            }

            if (!objectsEqual(nextValues, urlValues)) {
                return [urls.llmAnalyticsReviews(), nextValues, {}, { replace: true }]
            }
        },
    })),

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
        actions.loadScoreDefinitionOptions()
    }),
])
