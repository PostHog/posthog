import { actions, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingAssignmentRule, ErrorTrackingRuleType } from '../rules/types'
import type { assignmentRuleModalLogicType } from './assignmentRuleModalLogicType'

function emptyRule(orderKey: number = 0): ErrorTrackingAssignmentRule {
    return {
        id: 'new',
        filters: { type: FilterLogicalOperator.Or, values: [] },
        assignee: null,
        disabled_data: null,
        order_key: orderKey,
    }
}

export const assignmentRuleModalLogic = kea<assignmentRuleModalLogicType>([
    props({}),
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
    }),

    reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        rule: [
            emptyRule() as ErrorTrackingAssignmentRule,
            {
                openModal: (_, { rule }) => rule ?? emptyRule(),
                updateRule: (_, { rule }) => rule,
            },
        ],
    }),

    loaders(({ values }) => ({
        matchResult: [
            null as { exceptionCount: number; issueCount: number } | null,
            {
                loadMatchCount: async () => {
                    const filters = values.rule.filters as UniversalFiltersGroup
                    const properties = filters.values as AnyPropertyFilter[]

                    if (properties.length === 0) {
                        return null
                    }

                    const response = await api.query({
                        kind: NodeKind.EventsQuery,
                        event: '$exception',
                        select: ['count()', 'count(distinct properties.$exception_issue_id)'],
                        properties,
                        after: '-7d',
                    })

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
                    const ruleType = ErrorTrackingRuleType.Assignment

                    if (rule.id === 'new') {
                        await api.errorTracking.createRule(ruleType, rule)
                    } else {
                        await api.errorTracking.updateRule(ruleType, rule)
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
    })),

    selectors({
        hasFilters: [
            (s) => [s.rule],
            (rule): boolean => {
                const filters = rule.filters as UniversalFiltersGroup
                return (filters.values?.length ?? 0) > 0
            },
        ],
        hasAssignee: [
            (s) => [s.rule],
            (rule): boolean => {
                return rule.assignee !== null
            },
        ],
    }),
])
