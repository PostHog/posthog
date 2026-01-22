/**
 * Backward compatibility wrapper for llmAnalyticsLogic
 *
 * This file re-exports values and actions from the new split logics to maintain
 * backward compatibility during the migration period. All new code should import
 * from the individual tab logics directly:
 *
 * - llmAnalyticsSharedLogic: Shared filters and state (dateFilter, propertyFilters, etc.)
 * - llmAnalyticsDashboardLogic: Dashboard tiles and refresh functionality
 * - llmAnalyticsGenerationsLogic: Generations tab state
 * - llmAnalyticsTracesTabLogic: Traces tab state
 * - llmAnalyticsUsersLogic: Users tab state
 * - llmAnalyticsErrorsLogic: Errors tab state
 * - llmAnalyticsSessionsViewLogic: Sessions tab state
 */
import { connect, kea, key, path, props, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import type { llmAnalyticsLogicType } from './llmAnalyticsLogicType'
import { LLMAnalyticsSharedLogicProps, llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsDashboardLogic } from './tabs/llmAnalyticsDashboardLogic'
import { llmAnalyticsErrorsLogic } from './tabs/llmAnalyticsErrorsLogic'
import { llmAnalyticsGenerationsLogic } from './tabs/llmAnalyticsGenerationsLogic'
import { llmAnalyticsSessionsViewLogic } from './tabs/llmAnalyticsSessionsViewLogic'
import { llmAnalyticsTracesTabLogic } from './tabs/llmAnalyticsTracesTabLogic'
import { llmAnalyticsUsersLogic } from './tabs/llmAnalyticsUsersLogic'

// Re-export constants and functions for backward compatibility
export { LLM_ANALYTICS_DATA_COLLECTION_NODE_ID } from './llmAnalyticsSharedLogic'
export { getDefaultGenerationsColumns } from './tabs/llmAnalyticsGenerationsLogic'
export type { QueryTile } from './tabs/llmAnalyticsDashboardLogic'

export interface LLMAnalyticsLogicProps extends LLMAnalyticsSharedLogicProps {}

/**
 * @deprecated Use individual tab logics instead:
 * - llmAnalyticsSharedLogic for shared state (filters, date range)
 * - llmAnalyticsDashboardLogic for dashboard tiles
 * - llmAnalyticsGenerationsLogic for generations tab
 * - llmAnalyticsTracesTabLogic for traces tab
 * - llmAnalyticsUsersLogic for users tab
 * - llmAnalyticsErrorsLogic for errors tab
 * - llmAnalyticsSessionsViewLogic for sessions tab
 */
export const llmAnalyticsLogic = kea<llmAnalyticsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmAnalyticsLogic']),
    props({} as LLMAnalyticsLogicProps),
    key((props: LLMAnalyticsLogicProps) => props?.personId || 'llmAnalyticsScene'),
    connect((props: LLMAnalyticsLogicProps) => ({
        values: [
            // Shared logic values
            llmAnalyticsSharedLogic(props),
            [
                'dateFilter',
                'dashboardDateFilter',
                'shouldFilterTestAccounts',
                'shouldFilterSupportTraces',
                'propertyFilters',
                'activeTab',
                'breadcrumbs',
                'hasSentAiGenerationEvent',
                'hasSentAiGenerationEventLoading',
            ],
            // Dashboard logic values
            llmAnalyticsDashboardLogic,
            [
                'tiles',
                'refreshStatus',
                'newestRefreshed',
                'isRefreshing',
                'selectedDashboardId',
                'availableDashboards',
                'availableDashboardsLoading',
            ],
            // Generations logic values
            llmAnalyticsGenerationsLogic,
            ['generationsQuery', 'generationsColumns', 'generationsSort', 'expandedGenerationIds', 'loadedTraces'],
            // Users logic values
            llmAnalyticsUsersLogic,
            ['usersQuery', 'usersSort'],
            // Errors logic values
            llmAnalyticsErrorsLogic,
            ['errorsQuery', 'errorsSort'],
            // Sessions view logic values
            // Note: expandedGenerationIds is intentionally not connected here
            // to avoid collision with generations logic. Sessions scene should
            // use llmAnalyticsSessionsViewLogic directly.
            llmAnalyticsSessionsViewLogic,
            [
                'sessionsQuery',
                'sessionsSort',
                'expandedSessionIds',
                'expandedTraceIds',
                'sessionTraces',
                'fullTraces',
                'loadingSessionTraces',
                'loadingFullTraces',
            ],
            // Feature flags for selectors
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
        actions: [
            // Shared logic actions
            llmAnalyticsSharedLogic(props),
            [
                'setDates',
                'setShouldFilterTestAccounts',
                'setShouldFilterSupportTraces',
                'setPropertyFilters',
                'loadAIEventDefinition',
            ],
            // Dashboard logic actions
            llmAnalyticsDashboardLogic,
            ['refreshAllDashboardItems', 'setRefreshStatus', 'loadLLMDashboards'],
            // Generations logic actions
            llmAnalyticsGenerationsLogic,
            [
                'setGenerationsQuery',
                'setGenerationsColumns',
                'setGenerationsSort',
                'toggleGenerationExpanded',
                'setLoadedTrace',
                'clearExpandedGenerations',
            ],
            // Users logic actions
            llmAnalyticsUsersLogic,
            ['setUsersSort'],
            // Errors logic actions
            llmAnalyticsErrorsLogic,
            ['setErrorsSort'],
            // Traces tab logic actions
            llmAnalyticsTracesTabLogic,
            ['setTracesQuery'],
            // Sessions view logic actions
            // Note: toggleGenerationExpanded is intentionally not connected here
            // to avoid collision with generations logic. Sessions scene should
            // use llmAnalyticsSessionsViewLogic directly.
            llmAnalyticsSessionsViewLogic,
            [
                'setSessionsSort',
                'toggleSessionExpanded',
                'toggleTraceExpanded',
                'loadSessionTraces',
                'loadSessionTracesSuccess',
                'loadSessionTracesFailure',
                'loadFullTrace',
                'loadFullTraceSuccess',
                'loadFullTraceFailure',
            ],
        ],
    })),

    // Selectors that need to be computed from connected logics
    selectors({
        // Traces query needs to be computed here to support personId/group props
        tracesQuery: [
            (s) => [s.tracesQueryOverride, s.defaultTracesQuery],
            (override, defQuery) => override || defQuery,
        ],

        tracesQueryOverride: [() => [llmAnalyticsTracesTabLogic.selectors.tracesQueryOverride], (override) => override],

        defaultTracesQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.shouldFilterSupportTraces,
                s.propertyFilters,
                (_, props) => props.personId,
                (_, props) => props.group,
                s.groupsTaxonomicTypes,
                s.featureFlags,
                s.user,
            ],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                shouldFilterSupportTraces: boolean,
                propertyFilters,
                personId: string | undefined,
                group: { groupKey: string; groupTypeIndex: number } | undefined,
                groupsTaxonomicTypes: TaxonomicFilterGroupType[],
                featureFlags: { [flag: string]: boolean | string | undefined },
                user: { is_impersonated?: boolean } | null
            ): DataTableNode => {
                // For impersonated users (support agents), default to showing support traces
                // For regular users, always filter out support traces
                const filterSupportTraces = user?.is_impersonated ? shouldFilterSupportTraces : true

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.TracesQuery,
                        dateRange: {
                            date_from: dateFilter.dateFrom || undefined,
                            date_to: dateFilter.dateTo || undefined,
                        },
                        filterTestAccounts: shouldFilterTestAccounts ?? false,
                        filterSupportTraces,
                        properties: propertyFilters,
                        personId: personId ?? undefined,
                        groupKey: group?.groupKey,
                        groupTypeIndex: group?.groupTypeIndex,
                    },
                    columns: [
                        'id',
                        'traceName',
                        ...(featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT]
                            ? ['inputState', 'outputState']
                            : []),
                        'person',
                        'errors',
                        'totalLatency',
                        'usage',
                        'totalCost',
                        'timestamp',
                    ],
                    showDateRange: true,
                    showReload: true,
                    showSearch: true,
                    showTestAccountFilters: true,
                    showExport: true,
                    showOpenEditorButton: false,
                    showColumnConfigurator: false,
                    showPropertyFilter: [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ],
                }
            },
        ],
    }),
])
