import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsTracesTabLogicType } from './llmAnalyticsTracesTabLogicType'

export interface LLMAnalyticsTracesTabLogicProps {
    personId?: string
    group?: {
        groupKey: string
        groupTypeIndex: number
    }
}

export const llmAnalyticsTracesTabLogic = kea<llmAnalyticsTracesTabLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsTracesTabLogic']),
    key((props: LLMAnalyticsTracesTabLogicProps) => props?.personId || 'llmAnalyticsScene'),
    props({} as LLMAnalyticsTracesTabLogicProps),
    connect((props: LLMAnalyticsTracesTabLogicProps) => ({
        values: [
            llmAnalyticsSharedLogic(props),
            ['dateFilter', 'shouldFilterTestAccounts', 'shouldFilterSupportTraces', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
        ],
    })),

    actions({
        setTracesQuery: (query: DataTableNode) => ({ query }),
    }),

    reducers({
        tracesQueryOverride: [
            null as DataTableNode | null,
            {
                setTracesQuery: (_, { query }) => query,
            },
        ],
    }),

    selectors({
        tracesQuery: [
            (s) => [s.tracesQueryOverride, s.defaultTracesQuery],
            (override, defQuery) => override || defQuery,
        ],

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
