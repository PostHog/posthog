import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { FilterLogicalOperator } from '~/types'

import type { rulesLogicType } from './rulesLogicType'
import { ErrorTrackingRule, ErrorTrackingRuleNew, ErrorTrackingRuleType, ErrorTrackingRulesLogicProps } from './types'

function createNewRule(ruleType: ErrorTrackingRuleType, order_key: number): ErrorTrackingRuleNew {
    switch (ruleType) {
        case 'assignment_rules':
            return {
                id: 'new',
                assignee: null,
                filters: { type: FilterLogicalOperator.Or, values: [] },
                order_key,
            }
        case 'grouping_rules':
            return {
                id: 'new',
                assignee: null,
                description: '',
                filters: { type: FilterLogicalOperator.And, values: [] },
                order_key,
            }
        case 'suppression_rules':
            return {
                id: 'new',
                filters: { type: FilterLogicalOperator.Or, values: [] },
                order_key,
            }
        default:
            throw new Error(`Unsupported rule type: ${ruleType}`)
    }
}

export const rulesLogic = kea<rulesLogicType>([
    props({} as ErrorTrackingRulesLogicProps),
    key(({ ruleType }) => ruleType),
    path((key) => [
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'rules',
        'rulesLogic',
        key,
    ]),

    actions({
        addRule: true,
        startReorderingRules: true,
        cancelReorderingRules: true,
        setRuleEditable: (id: ErrorTrackingRule['id']) => ({ id }),
        unsetRuleEditable: (id: ErrorTrackingRule['id']) => ({ id }),
        updateLocalRule: (rule: ErrorTrackingRule) => ({ rule }),
        reorderLocalRules: (rules: ErrorTrackingRule[]) => ({ rules }),
        _setLocalRules: (rules: ErrorTrackingRule[]) => ({ rules }),
    }),

    reducers({
        localRules: [[] as ErrorTrackingRule[], { _setLocalRules: (_, { rules }) => rules }],
        isReorderingRules: [
            false,
            {
                startReorderingRules: () => true,
                cancelReorderingRules: () => false,
                finishReorderingRulesSuccess: () => false,
            },
        ],
        initialLoadComplete: [
            false,
            {
                loadRules: () => false,
                loadRulesSuccess: () => true,
                loadRulesFailure: () => true,
            },
        ],
    }),

    loaders(({ props, values }) => ({
        rules: [
            [] as ErrorTrackingRule[],
            {
                loadRules: async () => {
                    const { results: rules } = await api.errorTracking.rules(props.ruleType)
                    return rules
                },
                saveRule: async (id) => {
                    const rule = values.localRules.find((r) => r.id === id)
                    const newValues = [...values.rules]
                    if (rule) {
                        if (rule.id === 'new') {
                            const newRule = await api.errorTracking.createRule(props.ruleType, rule)
                            return [...newValues, newRule]
                        }
                        await api.errorTracking.updateRule(props.ruleType, rule)
                        return newValues.map((r) => (r.id === rule.id ? rule : r))
                    }
                    return newValues
                },
                deleteRule: async (id) => {
                    if (id !== 'new') {
                        await api.errorTracking.deleteRule(props.ruleType, id)
                    }
                    const newValues = [...values.rules]
                    return newValues.filter((v) => v.id !== id)
                },
                finishReorderingRules: async () => {
                    const rules = values.localRules
                    const ruleOrders = Object.fromEntries(rules.map((r) => [r.id, r.order_key]))
                    await api.errorTracking.reorderRules(props.ruleType, ruleOrders)
                    return rules
                },
            },
        ],
    })),

    listeners(({ props, values, actions }) => ({
        addRule: () => {
            actions._setLocalRules([...values.localRules, createNewRule(props.ruleType, values.rules.length)])
        },
        saveRuleSuccess: ({ payload: id }) => {
            const localRules = [...values.localRules]
            const newEditingRules = localRules.filter((v) => v.id !== id)
            actions._setLocalRules(newEditingRules)
        },
        deleteRuleSuccess: ({ payload: id }) => {
            const localRules = [...values.localRules]
            const newEditingRules = localRules.filter((v) => v.id !== id)
            actions._setLocalRules(newEditingRules)
        },
        setRuleEditable: ({ id }) => {
            const rule = values.rules.find((r) => r.id === id)
            if (rule) {
                actions._setLocalRules([...values.localRules, rule])
            }
        },
        unsetRuleEditable: ({ id }) => {
            const newLocalRules = [...values.localRules]
            const index = newLocalRules.findIndex((r) => r.id === id)
            if (index >= 0) {
                newLocalRules.splice(index, 1)
                actions._setLocalRules(newLocalRules)
            }
        },
        updateLocalRule: ({ rule }) => {
            const newEditingRules = [...values.localRules]
            const index = newEditingRules.findIndex((r) => r.id === rule.id)

            if (index >= 0) {
                newEditingRules.splice(index, 1, rule)
                actions._setLocalRules(newEditingRules)
            }
        },
        reorderLocalRules: ({ rules }) => {
            const reorderedRules = rules.map((r, index) => ({ ...r, order_key: index }))
            actions._setLocalRules(reorderedRules)
        },
        startReorderingRules: () => actions._setLocalRules([...values.rules]),
        cancelReorderingRules: () => actions._setLocalRules([]),
        finishReorderingRulesSuccess: () => actions._setLocalRules([]),
    })),

    selectors({
        allRules: [
            (s) => [s.localRules, s.rules],
            (localRules, rules): ErrorTrackingRule[] => {
                const uniqueRules = new Map([...rules, ...localRules].map((item) => [item.id, item]))
                return Array.from(uniqueRules.values()).sort((a, b) => a.order_key - b.order_key)
            },
        ],
        hasNewRule: [(s) => [s.allRules], (allRules): boolean => allRules.some((r) => r.id === 'new')],
    }),
])
