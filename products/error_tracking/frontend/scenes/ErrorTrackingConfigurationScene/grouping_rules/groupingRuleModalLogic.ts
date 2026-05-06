import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingGroupingRule, ErrorTrackingRuleType } from '../rules/types'
import type { groupingRuleModalLogicType } from './groupingRuleModalLogicType'

function emptyRule(orderKey: number = 0): ErrorTrackingGroupingRule {
    return {
        id: 'new',
        filters: { type: FilterLogicalOperator.And, values: [] },
        assignee: null,
        disabled_data: null,
        order_key: orderKey,
    }
}

export const groupingRuleModalLogic = kea<groupingRuleModalLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'grouping_rules',
        'groupingRuleModalLogic',
    ]),

    actions({
        openModal: (rule?: ErrorTrackingGroupingRule) => ({ rule: rule ?? null }),
        closeModal: true,
        updateRule: (rule: ErrorTrackingGroupingRule) => ({ rule }),
        increaseDateRange: true,
    }),

    reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        rule: [
            emptyRule() as ErrorTrackingGroupingRule,
            {
                openModal: (_: ErrorTrackingGroupingRule, { rule }: { rule: ErrorTrackingGroupingRule | null }) =>
                    rule ?? emptyRule(),
                updateRule: (_: ErrorTrackingGroupingRule, { rule }: { rule: ErrorTrackingGroupingRule }) => rule,
            },
        ],
        dateRange: [
            '-7d' as string,
            {
                openModal: () => '-7d',
                updateRule: () => '-7d',
                increaseDateRange: (state: string) => {
                    const next: Record<string, string> = { '-7d': '-30d', '-30d': '-90d' }
                    return next[state] ?? state
                },
            },
        ],
    }),

    loaders(({ values }) => ({
        matchResult: [
            null as { exceptionCount: number; issueCount: number } | null,
            {
                loadMatchCount: async () => {
                    const filters = values.rule.filters as UniversalFiltersGroup
                    const properties = (filters.values as AnyPropertyFilter[]) ?? []

                    const query: Record<string, any> = {
                        kind: NodeKind.EventsQuery,
                        event: '$exception',
                        select: ['count()', 'count(distinct properties.$exception_issue_id)'],
                        after: values.dateRange,
                        tags: { productKey: ProductKey.ERROR_TRACKING },
                    }

                    if (properties.length > 0) {
                        query.fixedProperties = [
                            { type: filters.type ?? FilterLogicalOperator.And, values: properties },
                        ]
                    } else {
                        return null
                    }

                    const response = (await api.query(query)) as Record<string, any>

                    return {
                        exceptionCount: response.results?.[0]?.[0] ?? 0,
                        issueCount: response.results?.[0]?.[1] ?? 0,
                    }
                },
                resetMatchCount: () => null,
            },
        ],
        saving: [
            false,
            {
                saveRule: async () => {
                    const rule = values.rule
                    if (rule.id === 'new') {
                        await api.errorTracking.createRule(ErrorTrackingRuleType.Grouping, rule)
                    } else {
                        await api.errorTracking.updateRule(ErrorTrackingRuleType.Grouping, rule)
                    }
                    return true
                },
            },
        ],
        deleting: [
            false,
            {
                deleteRule: async () => {
                    const rule = values.rule
                    await api.errorTracking.deleteRule(ErrorTrackingRuleType.Grouping, rule.id)
                    return true
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        saveRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Grouping }).actions.loadRules()
        },
        deleteRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Grouping }).actions.loadRules()
        },
        openModal: () => {
            actions.resetMatchCount()
        },
        updateRule: () => {
            actions.resetMatchCount()
        },
        increaseDateRange: () => {
            actions.loadMatchCount()
        },
    })),

    selectors({
        hasFilters: [
            (s) => [s.rule],
            (rule: ErrorTrackingGroupingRule): boolean => {
                const filters = rule.filters as UniversalFiltersGroup
                return (filters.values?.length ?? 0) > 0
            },
        ],
    }),
])
