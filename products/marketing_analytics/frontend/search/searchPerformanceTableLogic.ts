import { LogicWrapper, MakeLogicType, connect, kea, key, listeners, path, props, propsChanged, selectors } from 'kea'

import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import {
    DataNodeLogicProps,
    dataNodeLogic,
    dataNodeLogicActions,
    dataNodeLogicType,
} from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    ConversionGoalFilter,
    MarketingAnalyticsSearchConversionGoal,
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchQueryResponse,
    MarketingAnalyticsSearchRow,
} from '~/queries/schema/schema-general'

import { searchPerformanceRowKey } from './searchPerformance'

export interface SearchPerformanceTableLogicProps {
    query: MarketingAnalyticsSearchQuery
    queryKey: string
}

function dataProps({ query, queryKey }: SearchPerformanceTableLogicProps, conversions: boolean): DataNodeLogicProps {
    return {
        key: conversions ? `${queryKey}-posthog-conversions` : queryKey,
        query: conversions
            ? query
            : {
                  ...query,
                  includePostHogConversions: false,
                  normalizePageUrls: query.normalizePageUrls || query.includePostHogConversions,
              },
        doNotLoad: conversions && !query.includePostHogConversions,
        dataNodeCollectionId: conversions ? undefined : MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    }
}

export interface searchPerformanceTableLogicValues extends Pick<
    dataNodeLogicType['values'],
    'responseLoading' | 'responseError' | 'responseErrorObject' | 'queryId'
> {
    rawResponse: dataNodeLogicType['values']['response']
    rawConversionsResponse: dataNodeLogicType['values']['response']
    conversionsResponseLoading: boolean
    conversionsError: dataNodeLogicType['values']['responseError']
    conversionsErrorObject: dataNodeLogicType['values']['responseErrorObject']
    conversionsQueryId: string | null
    conversion_goals: ConversionGoalFilter[]
    baseDataNodeProps: DataNodeLogicProps
    conversionsEnabled: boolean
    conversionsLoading: boolean
    searchResponse: MarketingAnalyticsSearchQueryResponse | null
    conversionsResponse: MarketingAnalyticsSearchQueryResponse | null
    goals: MarketingAnalyticsSearchConversionGoal[]
    rows: MarketingAnalyticsSearchRow[]
}

export interface searchPerformanceTableLogicActions extends Pick<dataNodeLogicActions, 'loadData'> {
    loadConversions: dataNodeLogicActions['loadData']
}

export type searchPerformanceTableLogicType = MakeLogicType<
    searchPerformanceTableLogicValues,
    searchPerformanceTableLogicActions,
    SearchPerformanceTableLogicProps
>

export const searchPerformanceTableLogic: LogicWrapper<searchPerformanceTableLogicType> =
    kea<searchPerformanceTableLogicType>([
        props({} as SearchPerformanceTableLogicProps),
        key(({ queryKey }) => queryKey),
        path((key) => ['products', 'marketingAnalytics', 'searchPerformanceTableLogic', key]),
        connect((props: SearchPerformanceTableLogicProps) => ({
            values: [
                dataNodeLogic(dataProps(props, false)),
                ['response as rawResponse', 'responseLoading', 'responseError', 'responseErrorObject', 'queryId'],
                dataNodeLogic(dataProps(props, true)),
                [
                    'response as rawConversionsResponse',
                    'responseLoading as conversionsResponseLoading',
                    'responseError as conversionsError',
                    'responseErrorObject as conversionsErrorObject',
                    'queryId as conversionsQueryId',
                ],
                marketingAnalyticsSettingsLogic,
                ['conversion_goals'],
            ],
            actions: [
                dataNodeLogic(dataProps(props, false)),
                ['loadData'],
                dataNodeLogic(dataProps(props, true)),
                ['loadData as loadConversions'],
            ],
        })),
        selectors({
            baseDataNodeProps: [
                (_, p) => [p.query, p.queryKey],
                (query, queryKey): DataNodeLogicProps => dataProps({ query, queryKey }, false),
            ],
            conversionsEnabled: [(_, p) => [p.query], (query): boolean => !!query.includePostHogConversions],
            conversionsLoading: [
                (s) => [
                    s.conversionsEnabled,
                    s.conversionsResponseLoading,
                    s.rawConversionsResponse,
                    s.conversionsError,
                ],
                (enabled, loading, response, error): boolean => enabled && !error && (loading || !response),
            ],
            searchResponse: [
                (s) => [s.rawResponse],
                (response): MarketingAnalyticsSearchQueryResponse | null =>
                    response as MarketingAnalyticsSearchQueryResponse | null,
            ],
            conversionsResponse: [
                (s) => [s.conversionsEnabled, s.conversionsLoading, s.conversionsError, s.rawConversionsResponse],
                (enabled, loading, error, response): MarketingAnalyticsSearchQueryResponse | null =>
                    enabled && !loading && !error ? (response as MarketingAnalyticsSearchQueryResponse | null) : null,
            ],
            goals: [
                (s) => [s.conversionsEnabled, s.conversionsResponse, s.conversion_goals],
                (
                    enabled: boolean,
                    response: MarketingAnalyticsSearchQueryResponse | null,
                    goals: ConversionGoalFilter[]
                ): MarketingAnalyticsSearchConversionGoal[] =>
                    !enabled
                        ? []
                        : (response?.posthogConversionGoals ??
                          goals
                              .filter((goal) => goal.kind !== 'DataWarehouseNode')
                              .slice(0, 5)
                              .map((goal) => ({ id: goal.conversion_goal_id, name: goal.conversion_goal_name }))),
            ],
            rows: [
                (s) => [s.searchResponse, s.conversionsResponse],
                (
                    response: MarketingAnalyticsSearchQueryResponse | null,
                    conversions: MarketingAnalyticsSearchQueryResponse | null
                ): MarketingAnalyticsSearchRow[] => {
                    const byRow = new Map(
                        conversions?.results.map((row) => [searchPerformanceRowKey(row), row.posthogConversions])
                    )
                    return (response?.results ?? []).map((row) => ({
                        ...row,
                        posthogConversions: byRow.get(searchPerformanceRowKey(row)),
                    }))
                },
            ],
        }),
        listeners(({ actions, values }) => ({
            loadData: ({ refresh }) => {
                if (values.conversionsEnabled && (refresh === 'force_async' || refresh === 'force_blocking')) {
                    actions.loadConversions(refresh)
                }
            },
        })),
        propsChanged(({ props }, oldProps) => {
            if (JSON.stringify(props.query) !== JSON.stringify(oldProps.query)) {
                const conversions = dataNodeLogic.findMounted({ key: `${props.queryKey}-posthog-conversions` })
                conversions?.actions.abortAnyRunningQuery()
                conversions?.actions.clearResponse()
                dataNodeLogic(dataProps(props, false))
                dataNodeLogic(dataProps(props, true))
            }
        }),
    ])
