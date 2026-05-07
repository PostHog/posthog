import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingAssignmentRule, ErrorTrackingRuleType } from '../rules/types'
import type { assignmentRuleModalLogicType } from './assignmentRuleModalLogicType'

function emptyRule(orderKey: number = 0): ErrorTrackingAssignmentRule {
    return {
        id: 'new',
        filters: { type: FilterLogicalOperator.And, values: [] },
        assignee: null,
        disabled_data: null,
        order_key: orderKey,
    }
}

export const assignmentRuleModalLogic = kea<assignmentRuleModalLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'assignment_rules',
        'assignmentRuleModalLogic',
    ]),

    actions({
        openModal: (rule?: ErrorTrackingAssignmentRule) => ({ rule: rule ?? null }),
        closeModal: true,
        updateRule: (rule: ErrorTrackingAssignmentRule) => ({ rule }),
        increaseDateRange: true,
    }),

    reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        rule: [
            emptyRule() as ErrorTrackingAssignmentRule,
            {
                openModal: (_: ErrorTrackingAssignmentRule, { rule }: { rule: ErrorTrackingAssignmentRule | null }) =>
                    rule ?? emptyRule(),
                updateRule: (_: ErrorTrackingAssignmentRule, { rule }: { rule: ErrorTrackingAssignmentRule }) => rule,
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
                        await api.errorTracking.createRule(ErrorTrackingRuleType.Assignment, rule)
                    } else {
                        await api.errorTracking.updateRule(ErrorTrackingRuleType.Assignment, rule)
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
                    await api.errorTracking.deleteRule(ErrorTrackingRuleType.Assignment, rule.id)
                    return true
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        saveRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Assignment }).actions.loadRules()
        },
        deleteRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Assignment }).actions.loadRules()
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
            (rule: ErrorTrackingAssignmentRule): boolean => {
                const filters = rule.filters as UniversalFiltersGroup
                return (filters.values?.length ?? 0) > 0
            },
        ],
        hasAssignee: [
            (s) => [s.rule],
            (rule: ErrorTrackingAssignmentRule): boolean => {
                return rule.assignee !== null
            },
        ],
    }),
])
