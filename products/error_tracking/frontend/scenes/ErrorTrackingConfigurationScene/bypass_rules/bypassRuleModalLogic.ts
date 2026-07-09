import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingBypassRule, ErrorTrackingRuleType } from '../rules/types'
import type { bypassRuleModalLogicType } from './bypassRuleModalLogicType'

function emptyRule(orderKey: number = 0): ErrorTrackingBypassRule {
    return {
        id: 'new',
        filters: { type: FilterLogicalOperator.Or, values: [] },
        disabled_data: null,
        order_key: orderKey,
    }
}

export const bypassRuleModalLogic = kea<bypassRuleModalLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'bypass_rules',
        'bypassRuleModalLogic',
    ]),

    actions({
        openModal: (rule?: ErrorTrackingBypassRule) => ({ rule: rule ?? null }),
        closeModal: true,
        updateRule: (rule: ErrorTrackingBypassRule) => ({ rule }),
    }),

    reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        rule: [
            emptyRule() as ErrorTrackingBypassRule,
            {
                openModal: (_: ErrorTrackingBypassRule, { rule }: { rule: ErrorTrackingBypassRule | null }) =>
                    rule ?? emptyRule(),
                updateRule: (_: ErrorTrackingBypassRule, { rule }: { rule: ErrorTrackingBypassRule }) => rule,
            },
        ],
    }),

    loaders(({ values }) => ({
        saving: [
            false,
            {
                saveRule: async () => {
                    const rule = values.rule
                    if (rule.id === 'new') {
                        await api.errorTracking.createRule(ErrorTrackingRuleType.Bypass, rule)
                    } else {
                        await api.errorTracking.updateRule(ErrorTrackingRuleType.Bypass, rule)
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
                    await api.errorTracking.deleteRule(ErrorTrackingRuleType.Bypass, rule.id)
                    return true
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        saveRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Bypass }).actions.loadRules()
        },
        deleteRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType: ErrorTrackingRuleType.Bypass }).actions.loadRules()
        },
    })),

    selectors({
        hasFilters: [
            (s) => [s.rule],
            (rule: ErrorTrackingBypassRule): boolean => {
                const filters = rule.filters as UniversalFiltersGroup
                return (filters.values?.length ?? 0) > 0
            },
        ],
    }),
])
