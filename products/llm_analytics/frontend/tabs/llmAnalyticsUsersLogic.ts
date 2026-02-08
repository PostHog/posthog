import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { SortDirection, SortState, llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsUsersLogicType } from './llmAnalyticsUsersLogicType'

export const llmAnalyticsUsersLogic = kea<llmAnalyticsUsersLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsUsersLogic']),
    connect(() => ({
        values: [
            llmAnalyticsSharedLogic,
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),

    actions({
        setUsersSort: (column: string, direction: SortDirection) => ({ column, direction }),
    }),

    reducers({
        usersSort: [
            { column: 'last_seen', direction: 'DESC' } as SortState,
            {
                setUsersSort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
    }),

    selectors({
        usersQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                s.usersSort,
                s.groupsTaxonomicTypes,
                s.featureFlags,
            ],
            (
                dateFilter,
                shouldFilterTestAccounts,
                propertyFilters,
                usersSort,
                groupsTaxonomicTypes,
                featureFlags: Record<string, boolean | string | undefined>
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: `
                SELECT
                    argMax(user_tuple, timestamp) as __llm_person,
                    tuple(
                        avgIf(sentiment_positive, event_name = '$ai_sentiment'),
                        avgIf(sentiment_neutral, event_name = '$ai_sentiment'),
                        avgIf(sentiment_negative, event_name = '$ai_sentiment'),
                        countIf(event_name = '$ai_sentiment'),
                        maxIf(sentiment_positive_max, event_name = '$ai_sentiment'),
                        maxIf(sentiment_negative_max, event_name = '$ai_sentiment')
                    ) as sentiment,
                    countDistinctIf(ai_trace_id, notEmpty(ai_trace_id) AND event_name = '$ai_generation') as traces,
                    countIf(event_name = '$ai_generation') as generations,
                    countIf((notEmpty(ai_error) OR ai_is_error = 'true') AND event_name = '$ai_generation') as errors,
                    round(sumIf(toFloat(ai_total_cost_usd), event_name = '$ai_generation'), 4) as total_cost,
                    minIf(timestamp, event_name = '$ai_generation') as first_seen,
                    maxIf(timestamp, event_name = '$ai_generation') as last_seen
                FROM (
                    SELECT
                        distinct_id,
                        event as event_name,
                        timestamp,
                        JSONExtractRaw(properties, '$ai_trace_id') as ai_trace_id,
                        JSONExtractRaw(properties, '$ai_total_cost_usd') as ai_total_cost_usd,
                        JSONExtractRaw(properties, '$ai_error') as ai_error,
                        JSONExtractString(properties, '$ai_is_error') as ai_is_error,
                        JSONExtractFloat(JSONExtractRaw(properties, '$ai_sentiment_scores'), 'positive') as sentiment_positive,
                        JSONExtractFloat(JSONExtractRaw(properties, '$ai_sentiment_scores'), 'neutral') as sentiment_neutral,
                        JSONExtractFloat(JSONExtractRaw(properties, '$ai_sentiment_scores'), 'negative') as sentiment_negative,
                        JSONExtractFloat(properties, '$ai_sentiment_positive_max_score') as sentiment_positive_max,
                        JSONExtractFloat(properties, '$ai_sentiment_negative_max_score') as sentiment_negative_max,
                        tuple(
                            distinct_id,
                            person.created_at,
                            person.properties
                        ) as user_tuple
                    FROM events
                    WHERE event IN ('$ai_generation', '$ai_sentiment') AND {filters}
                )
                GROUP BY distinct_id
                ORDER BY ${usersSort.column} ${usersSort.direction}
                LIMIT 50
                    `,
                    filters: {
                        dateRange: {
                            date_from: dateFilter.dateFrom || null,
                            date_to: dateFilter.dateTo || null,
                        },
                        filterTestAccounts: shouldFilterTestAccounts,
                        properties: propertyFilters,
                    },
                },
                columns: [
                    '__llm_person',
                    ...(featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SENTIMENT] ? ['sentiment'] : []),
                    'traces',
                    'generations',
                    'errors',
                    'total_cost',
                    'first_seen',
                    'last_seen',
                ],
                showDateRange: true,
                showReload: true,
                showSearch: true,
                showPropertyFilter: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.HogQLExpression,
                ],
                showTestAccountFilters: true,
                showExport: true,
                showColumnConfigurator: true,
                allowSorting: true,
            }),
        ],
    }),
])
