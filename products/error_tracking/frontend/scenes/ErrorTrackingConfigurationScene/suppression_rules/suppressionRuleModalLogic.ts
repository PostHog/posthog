import { actions, kea, listeners, path, reducers, selectors } from 'kea'
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
        sampling_rate: 1.0,
    }
}

export const suppressionRuleModalLogic = kea<suppressionRuleModalLogicType>([
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
        updateSamplingRate: (sampling_rate: number) => ({ sampling_rate }),
        increaseDateRange: true,
    }),

    reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        rule: [
            emptyRule() as ErrorTrackingSuppressionRule,
            {
                openModal: (_: ErrorTrackingSuppressionRule, { rule }: { rule: ErrorTrackingSuppressionRule | null }) =>
                    rule ?? emptyRule(),
                updateRule: (_: ErrorTrackingSuppressionRule, { rule }: { rule: ErrorTrackingSuppressionRule }) => rule,
                updateSamplingRate: (
                    state: ErrorTrackingSuppressionRule,
                    { sampling_rate }: { sampling_rate: number }
                ) => ({
                    ...state,
                    sampling_rate,
                }),
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
                    }

                    if (properties.length > 0) {
                        query.fixedProperties = [
                            { type: filters.type ?? FilterLogicalOperator.And, values: properties },
                        ]
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
                        await api.errorTracking.createRule(ErrorTrackingRuleType.Suppression, rule)
                    } else {
                        await api.errorTracking.updateRule(ErrorTrackingRuleType.Suppression, rule)
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
            (rule: ErrorTrackingSuppressionRule): boolean => {
                const filters = rule.filters as UniversalFiltersGroup
                return (filters.values?.length ?? 0) > 0
            },
        ],
    }),
])
