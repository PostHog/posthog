import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { Sorting } from 'lib/lemon-ui/LemonTable'

import { ApiConfig } from '~/lib/api'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { tabAwareActionToUrl } from '~/lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from '~/lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual, pluralize } from '~/lib/utils'
import { urls } from '~/scenes/urls'

import { llmAnalyticsScoreDefinitionsList } from '../generated/api'
import type { Kind01eEnumApi as ScoreDefinitionKind, PaginatedScoreDefinitionListApi } from '../generated/api.schemas'
import type { llmAnalyticsScoreDefinitionsLogicType } from './llmAnalyticsScoreDefinitionsLogicType'

export const SCORE_DEFINITIONS_PER_PAGE = 30

export interface ScoreDefinitionFilters {
    page: number
    search: string
    kind: ScoreDefinitionKind | ''
    archived: '' | 'true' | 'false'
    order_by: string
}

type ScoreDefinitionFilterInput = Omit<Partial<ScoreDefinitionFilters>, 'archived'> & {
    archived?: ScoreDefinitionFilters['archived'] | 'all' | boolean | null
}

const ALLOWED_ORDER_BY_VALUES = new Set([
    'name',
    '-name',
    'kind',
    '-kind',
    'created_at',
    '-created_at',
    'updated_at',
    '-updated_at',
    'current_version',
    '-current_version',
])

function cleanFilters(values: ScoreDefinitionFilterInput): ScoreDefinitionFilters {
    const orderBy = values.order_by && ALLOWED_ORDER_BY_VALUES.has(values.order_by) ? values.order_by : 'name'

    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        kind:
            values.kind === 'categorical' || values.kind === 'numeric' || values.kind === 'boolean' ? values.kind : '',
        archived:
            values.archived === 'all' || values.archived === ''
                ? ''
                : values.archived === undefined || values.archived === null
                  ? 'false'
                  : values.archived === 'true' || values.archived === true
                    ? 'true'
                    : values.archived === 'false' || values.archived === false
                      ? 'false'
                      : 'false',
        order_by: orderBy,
    }
}

function getUrlFilters(filters: ScoreDefinitionFilters): Record<string, unknown> {
    return {
        page: filters.page === 1 ? undefined : filters.page,
        search: filters.search || undefined,
        kind: filters.kind || undefined,
        archived: filters.archived === 'false' ? undefined : filters.archived === '' ? 'all' : 'true',
        order_by: filters.order_by === 'name' ? undefined : filters.order_by,
    }
}

export interface LLMAnalyticsScoreDefinitionsLogicProps {
    tabId?: string
}

export const llmAnalyticsScoreDefinitionsLogic = kea<llmAnalyticsScoreDefinitionsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'scoreDefinitions', 'llmAnalyticsScoreDefinitionsLogic']),
    props({} as LLMAnalyticsScoreDefinitionsLogicProps),
    key((props) => props.tabId ?? 'default'),

    actions({
        setFilters: (filters: Partial<ScoreDefinitionFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadScoreDefinitions: (debounce: boolean = true) => ({ debounce }),
    }),

    reducers({
        rawFilters: [
            null as Partial<ScoreDefinitionFilters> | null,
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
        scoreDefinitions: [
            { results: [], count: 0, next: null, previous: null } as PaginatedScoreDefinitionListApi,
            {
                loadScoreDefinitions: async ({ debounce }, breakpoint) => {
                    if (debounce && values.scoreDefinitions.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { filters } = values

                    return llmAnalyticsScoreDefinitionsList(String(ApiConfig.getCurrentTeamId()), {
                        search: filters.search || undefined,
                        kind: filters.kind || undefined,
                        archived: filters.archived === '' ? undefined : filters.archived === 'true' ? true : false,
                        order_by: filters.order_by,
                        offset: Math.max(0, (filters.page - 1) * SCORE_DEFINITIONS_PER_PAGE),
                        limit: SCORE_DEFINITIONS_PER_PAGE,
                    })
                },
            },
        ],
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<ScoreDefinitionFilters> | null): ScoreDefinitionFilters =>
                cleanFilters(rawFilters || {}),
        ],

        count: [
            (s) => [s.scoreDefinitions],
            (scoreDefinitions: PaginatedScoreDefinitionListApi) => scoreDefinitions.count,
        ],

        sorting: [
            (s) => [s.filters],
            (filters: ScoreDefinitionFilters): Sorting | null => {
                if (!filters.order_by) {
                    return {
                        columnKey: 'name',
                        order: 1,
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
            (filters: ScoreDefinitionFilters, count: number): PaginationManual => ({
                controlled: true,
                pageSize: SCORE_DEFINITIONS_PER_PAGE,
                currentPage: filters.page,
                entryCount: count,
            }),
        ],

        scoreDefinitionCountLabel: [
            (s) => [s.filters, s.count, s.scoreDefinitionsLoading],
            (filters: ScoreDefinitionFilters, count: number, loading: boolean): string => {
                if (loading) {
                    return ''
                }

                const start = (filters.page - 1) * SCORE_DEFINITIONS_PER_PAGE + 1
                const end = Math.min(filters.page * SCORE_DEFINITIONS_PER_PAGE, count)

                return count === 0 ? '0 scorers' : `${start}-${end} of ${pluralize(count, 'scorer')}`
            },
        ],
    }),

    listeners(({ asyncActions, values, selectors }) => ({
        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)

            if (!objectsEqual(oldFilters, values.filters)) {
                await asyncActions.loadScoreDefinitions(debounce)
            }
        },
    })),

    tabAwareActionToUrl(({ values }) => ({
        setFilters: () => {
            const nextValues = getUrlFilters(values.filters)
            const urlValues = getUrlFilters(cleanFilters(router.values.searchParams))

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
                actions.loadScoreDefinitions(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadScoreDefinitions()
    }),
])
