import { actions, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingRuleType, ErrorTrackingSuppressionRule } from '../rules/types'
import type { suppressionRuleModalLogicType } from './suppressionRuleModalLogicType'

function emptyRule(orderKey: number = 0): ErrorTrackingSuppressionRule {
    return {
        id: 'new',
        filters: { type: FilterLogicalOperator.Or, values: [] },
        disabled_data: null,
        order_key: orderKey,
    }
}

export const suppressionRuleModalLogic = kea<suppressionRuleModalLogicType>([
    props({}),
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'suppression_rules',
        'suppressionRuleModalLogic',
    ]),

    actions({
        openModal: (rule?: ErrorTrackingSuppressionRule) => ({ rule: rule ?? null }),
        closeModal: true,
        updateRule: (rule: ErrorTrackingSuppressionRule) => ({ rule }),
        increaseDateRange: true,
    }),

    reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        rule: [
            emptyRule() as ErrorTrackingSuppressionRule,
            {
                openModal: (_, { rule }) => rule ?? emptyRule(),
                updateRule: (_, { rule }) => rule,
            },
        ],
        dateRange: [
            '-7d' as string,
            {
                openModal: () => '-7d',
                updateRule: () => '-7d',
                increaseDateRange: (state) => {
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
                    const properties = filters.values as AnyPropertyFilter[]

                    if (properties.length === 0) {
                        return null
                    }

                    const response = await api.query({
                        kind: NodeKind.EventsQuery,
                        event: '$exception',
                        select: ['count()', 'count(distinct properties.$exception_issue_id)'],
                        properties,
                        after: values.dateRange,
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
                    const ruleType = ErrorTrackingRuleType.Suppression

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
                    await api.errorTracking.deleteRule(ErrorTrackingRuleType.Suppression, rule.id)
                    return true
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        saveRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Suppression }).actions.loadRules()
        },
        deleteRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Suppression }).actions.loadRules()
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
            (rule): boolean => {
                const filters = rule.filters as UniversalFiltersGroup
                return (filters.values?.length ?? 0) > 0
            },
        ],
    }),
])
