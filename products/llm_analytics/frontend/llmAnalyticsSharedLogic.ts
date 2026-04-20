import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual } from 'lib/utils'
import { hasRecentAIEvents } from 'lib/utils/aiEventsUtils'
import { sceneLogic } from 'scenes/sceneLogic'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { isAnyPropertyFilters } from '~/queries/schema-guards'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, Breadcrumb } from '~/types'

import type { llmAnalyticsSharedLogicType } from './llmAnalyticsSharedLogicType'

export const LLM_ANALYTICS_DATA_COLLECTION_NODE_ID = 'llm-analytics-data'

export type LLMAnalyticsTabId =
    | 'dashboard'
    | 'generations'
    | 'reviews'
    | 'traces'
    | 'users'
    | 'errors'
    | 'tools'
    | 'sentiment'
    | 'sessions'
    | 'playground'
    | 'datasets'
    | 'evaluations'
    | 'prompts'
    | 'clusters'

export type SortDirection = 'ASC' | 'DESC'

export interface SortState {
    column: string
    direction: SortDirection
}

const INITIAL_DASHBOARD_DATE_FROM = '-7d' as string | null
const INITIAL_EVENTS_DATE_FROM = '-1h' as string | null
const INITIAL_DATE_TO = null as string | null

export interface LLMAnalyticsSharedLogicProps {
    logicKey?: string
    tabId?: string
    personId?: string
    group?: {
        groupKey: string
        groupTypeIndex: number
    }
}

export const llmAnalyticsSharedLogic = kea<llmAnalyticsSharedLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmAnalyticsSharedLogic']),
    props({} as LLMAnalyticsSharedLogicProps),
    key((props: LLMAnalyticsSharedLogicProps) => `${props?.personId || 'llmAnalyticsScene'}::${props?.tabId || ''}`),
    connect(() => ({
        values: [
            sceneLogic,
            ['sceneKey'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
        ],
        actions: [teamLogic, ['addProductIntent'], filterTestAccountsDefaultsLogic, ['setLocalDefault']],
    })),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
        setShouldFilterSupportTraces: (shouldFilterSupportTraces: boolean) => ({ shouldFilterSupportTraces }),
        setPropertyFilters: (propertyFilters: AnyPropertyFilter[]) => ({ propertyFilters }),
        // Batched action for URL-to-state sync. Dispatched once from urlToAction
        // instead of multiple individual actions, producing a single actionToUrl
        // URL change instead of 3-4 separate ones.
        applyUrlState: (state: {
            propertyFilters: AnyPropertyFilter[]
            dateFrom: string | null
            dateTo: string | null
            shouldFilterTestAccounts: boolean
            datesChanged: boolean
        }) => state,
    }),

    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_EVENTS_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
                applyUrlState: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],

        dashboardDateFilter: [
            {
                dateFrom: INITIAL_DASHBOARD_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
                applyUrlState: (state, { dateFrom, dateTo, datesChanged }) =>
                    datesChanged ? { dateFrom, dateTo } : state,
            },
        ],

        shouldFilterTestAccounts: [
            false,
            {
                setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
                applyUrlState: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
            },
        ],

        shouldFilterSupportTraces: [
            false, // For impersonated users, default to NOT filtering (show support traces)
            {
                setShouldFilterSupportTraces: (_, { shouldFilterSupportTraces }) => shouldFilterSupportTraces,
            },
        ],

        propertyFilters: [
            [] as AnyPropertyFilter[],
            {
                setPropertyFilters: (_, { propertyFilters }) => propertyFilters,
                applyUrlState: (_, { propertyFilters }) => propertyFilters,
            },
        ],
    }),

    loaders(() => ({
        hasSentAiEvent: {
            __default: undefined as boolean | undefined,
            loadAIEventDefinition: async (): Promise<boolean> => {
                return hasRecentAIEvents()
            },
        },
    })),

    listeners(({ actions, values }) => ({
        loadAIEventDefinitionSuccess: ({ hasSentAiEvent }) => {
            if (hasSentAiEvent) {
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.IngestFirstLlmEvent)
            }
        },
        setShouldFilterTestAccounts: ({ shouldFilterTestAccounts }) => {
            const divergesFromEffectiveDefault = shouldFilterTestAccounts !== values.filterTestAccountsDefault
            if (divergesFromEffectiveDefault) {
                actions.setLocalDefault(shouldFilterTestAccounts)
            }
        },
    })),

    selectors({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey): LLMAnalyticsTabId => {
                if (sceneKey === 'llmAnalyticsGenerations') {
                    return 'generations'
                } else if (sceneKey === 'llmAnalyticsReviews') {
                    return 'reviews'
                } else if (sceneKey === 'llmAnalyticsTraces') {
                    return 'traces'
                } else if (sceneKey === 'llmAnalyticsUsers') {
                    return 'users'
                } else if (sceneKey === 'llmAnalyticsErrors') {
                    return 'errors'
                } else if (sceneKey === 'llmAnalyticsTools') {
                    return 'tools'
                } else if (sceneKey === 'llmAnalyticsSentiment') {
                    return 'sentiment'
                } else if (sceneKey === 'llmAnalyticsSessions') {
                    return 'sessions'
                } else if (sceneKey === 'llmAnalyticsPlayground') {
                    return 'playground'
                } else if (sceneKey === 'llmAnalyticsDatasets') {
                    return 'datasets'
                } else if (sceneKey === 'llmAnalyticsEvaluations') {
                    return 'evaluations'
                } else if (sceneKey === 'llmAnalyticsPrompts') {
                    return 'prompts'
                } else if (sceneKey === 'llmAnalyticsClusters') {
                    return 'clusters'
                }

                return 'dashboard'
            },
        ],

        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: 'llm_analytics',
                        name: 'LLM Analytics',
                        iconType: 'llm_analytics',
                    },
                ]
            },
        ],
    }),

    tabAwareUrlToAction(({ actions, values }) => {
        const KNOWN_PARAMS = new Set(['filters', 'date_from', 'date_to', 'filter_test_accounts'])

        function applySearchParams(
            searchParams: Record<string, unknown>,
            options?: { stripStaleParams?: boolean }
        ): void {
            const { filters, date_from, date_to, filter_test_accounts } = searchParams

            const parsedFilters = isAnyPropertyFilters(filters) ? filters : []
            const newDateFrom = (date_from as string | null) || INITIAL_EVENTS_DATE_FROM
            const newDateTo = (date_to as string | null) || INITIAL_DATE_TO
            const filterTestAccountsValue = [true, 'true', 1, '1'].includes(
                filter_test_accounts as string | number | boolean
            )

            const filtersChanged = !objectsEqual(parsedFilters, values.propertyFilters)
            const datesChanged = newDateFrom !== values.dateFilter.dateFrom || newDateTo !== values.dateFilter.dateTo
            const testAccountsChanged = filterTestAccountsValue !== values.shouldFilterTestAccounts

            if (filtersChanged || datesChanged || testAccountsChanged) {
                // Dispatch a single batched action so actionToUrl produces one URL
                // change instead of up to 3 separate ones. The actionToUrl handler
                // for applyUrlState emits only known params, which also strips any
                // stale params carried over from other pages.
                actions.applyUrlState({
                    propertyFilters: parsedFilters,
                    dateFrom: newDateFrom,
                    dateTo: newDateTo,
                    shouldFilterTestAccounts: filterTestAccountsValue,
                    datesChanged,
                })
            } else if (options?.stripStaleParams !== false) {
                // No state changed, but stale params may still need stripping
                // (e.g. event, timestamp, msg from trace view).
                const hasStaleParams = Object.keys(searchParams).some((key) => !KNOWN_PARAMS.has(key))
                if (hasStaleParams) {
                    const cleanParams: Record<string, unknown> = {}
                    for (const key of KNOWN_PARAMS) {
                        if (searchParams[key] !== undefined) {
                            cleanParams[key] = searchParams[key]
                        }
                    }
                    router.actions.replace(router.values.location.pathname, cleanParams)
                }
            }
        }

        return {
            [urls.llmAnalyticsDashboard()]: (_, searchParams) => {
                applySearchParams(searchParams)
                actions.addProductIntent({
                    product_type: ProductKey.LLM_ANALYTICS,
                    intent_context: ProductIntentContext.LLM_ANALYTICS_VIEWED,
                })
            },
            [urls.llmAnalyticsGenerations()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsReviews()]: (_, searchParams) =>
                applySearchParams(searchParams, { stripStaleParams: false }),
            [urls.llmAnalyticsTraces()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsUsers()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsErrors()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsTools()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsSentiment()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsSessions()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsPlayground()]: (_, searchParams) => applySearchParams(searchParams),
        }
    }),

    tabAwareActionToUrl(() => {
        // Only preserve params that belong to the shared logic — drop stale
        // params from other pages (e.g. event, timestamp, msg from trace view).
        function sharedSearchParams(): Record<string, unknown> {
            const { filters, date_from, date_to, filter_test_accounts } = router.values.searchParams
            return { filters, date_from, date_to, filter_test_accounts }
        }

        return {
            applyUrlState: ({ propertyFilters, dateFrom, dateTo, shouldFilterTestAccounts }) => [
                router.values.location.pathname,
                {
                    filters: propertyFilters.length > 0 ? propertyFilters : undefined,
                    date_from: dateFrom === INITIAL_EVENTS_DATE_FROM ? undefined : dateFrom || undefined,
                    date_to: dateTo || undefined,
                    filter_test_accounts: shouldFilterTestAccounts ? 'true' : undefined,
                },
            ],
            setPropertyFilters: ({ propertyFilters }) => [
                router.values.location.pathname,
                {
                    ...sharedSearchParams(),
                    filters: propertyFilters.length > 0 ? propertyFilters : undefined,
                },
            ],
            setDates: ({ dateFrom, dateTo }) => [
                router.values.location.pathname,
                {
                    ...sharedSearchParams(),
                    date_from: dateFrom === INITIAL_EVENTS_DATE_FROM ? undefined : dateFrom || undefined,
                    date_to: dateTo || undefined,
                },
            ],
            setShouldFilterTestAccounts: ({ shouldFilterTestAccounts }) => [
                router.values.location.pathname,
                {
                    ...sharedSearchParams(),
                    filter_test_accounts: shouldFilterTestAccounts ? 'true' : undefined,
                },
            ],
        }
    }),

    afterMount(({ actions, values }) => {
        actions.loadAIEventDefinition()
        globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.TrackCosts)

        // Track product intent when dashboard is viewed
        if (values.activeTab === 'dashboard') {
            actions.addProductIntent({
                product_type: ProductKey.LLM_ANALYTICS,
                intent_context: ProductIntentContext.LLM_ANALYTICS_VIEWED,
            })
        }

        const urlHasTestAccountsParam = 'filter_test_accounts' in router.values.searchParams
        if (!urlHasTestAccountsParam && values.filterTestAccountsDefault !== values.shouldFilterTestAccounts) {
            actions.setShouldFilterTestAccounts(values.filterTestAccountsDefault)
        }
    }),
])
