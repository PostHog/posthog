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
    | 'traces'
    | 'users'
    | 'errors'
    | 'sessions'
    | 'playground'
    | 'datasets'
    | 'evaluations'
    | 'prompts'
    | 'settings'
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
    key((props: LLMAnalyticsSharedLogicProps) => props?.personId || 'llmAnalyticsScene'),
    connect(() => ({
        values: [sceneLogic, ['sceneKey'], featureFlagLogic, ['featureFlags'], userLogic, ['user']],
        actions: [teamLogic, ['addProductIntent']],
    })),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
        setShouldFilterSupportTraces: (shouldFilterSupportTraces: boolean) => ({ shouldFilterSupportTraces }),
        setPropertyFilters: (propertyFilters: AnyPropertyFilter[]) => ({ propertyFilters }),
    }),

    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_EVENTS_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],

        dashboardDateFilter: [
            {
                dateFrom: INITIAL_DASHBOARD_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],

        shouldFilterTestAccounts: [
            false,
            {
                setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
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

    listeners(() => ({
        loadAIEventDefinitionSuccess: ({ hasSentAiEvent }) => {
            if (hasSentAiEvent) {
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.IngestFirstLlmEvent)
            }
        },
    })),

    selectors({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey): LLMAnalyticsTabId => {
                if (sceneKey === 'llmAnalyticsGenerations') {
                    return 'generations'
                } else if (sceneKey === 'llmAnalyticsTraces') {
                    return 'traces'
                } else if (sceneKey === 'llmAnalyticsUsers') {
                    return 'users'
                } else if (sceneKey === 'llmAnalyticsErrors') {
                    return 'errors'
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
                } else if (sceneKey === 'llmAnalyticsSettings') {
                    return 'settings'
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
        function applySearchParams({
            filters,
            date_from,
            date_to,
            filter_test_accounts,
        }: Record<string, unknown>): void {
            const parsedFilters = isAnyPropertyFilters(filters) ? filters : []

            if (!objectsEqual(parsedFilters, values.propertyFilters)) {
                actions.setPropertyFilters(parsedFilters)
            }

            if (
                (date_from || INITIAL_EVENTS_DATE_FROM) !== values.dateFilter.dateFrom ||
                (date_to || INITIAL_DATE_TO) !== values.dateFilter.dateTo
            ) {
                actions.setDates(
                    (date_from as string | null) || INITIAL_EVENTS_DATE_FROM,
                    (date_to as string | null) || INITIAL_DATE_TO
                )
            }

            const filterTestAccountsValue = [true, 'true', 1, '1'].includes(
                filter_test_accounts as string | number | boolean
            )

            if (filterTestAccountsValue !== values.shouldFilterTestAccounts) {
                actions.setShouldFilterTestAccounts(filterTestAccountsValue)
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
            [urls.llmAnalyticsTraces()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsUsers()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsErrors()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsSessions()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsPlayground()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsSettings()]: () => {},
        }
    }),

    tabAwareActionToUrl(() => ({
        setPropertyFilters: ({ propertyFilters }) => [
            router.values.location.pathname,
            {
                ...router.values.searchParams,
                filters: propertyFilters.length > 0 ? propertyFilters : undefined,
            },
        ],
        setDates: ({ dateFrom, dateTo }) => [
            router.values.location.pathname,
            {
                ...router.values.searchParams,
                date_from: dateFrom === INITIAL_EVENTS_DATE_FROM ? undefined : dateFrom || undefined,
                date_to: dateTo || undefined,
            },
        ],
        setShouldFilterTestAccounts: ({ shouldFilterTestAccounts }) => [
            router.values.location.pathname,
            {
                ...router.values.searchParams,
                filter_test_accounts: shouldFilterTestAccounts ? 'true' : undefined,
            },
        ],
    })),

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
    }),
])
