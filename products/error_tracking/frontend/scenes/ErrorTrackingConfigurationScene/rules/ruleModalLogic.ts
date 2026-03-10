import { actions, listeners, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, UniversalFiltersGroup } from '~/types'

import { rulesLogic } from './rulesLogic'
import { ErrorTrackingBaseRule, ErrorTrackingRuleType } from './types'

type KeaBuilder = (logic: any) => void

export function ruleModalActions(): KeaBuilder {
    return actions({
        openModal: (rule?: ErrorTrackingBaseRule) => ({ rule: rule ?? null }),
        closeModal: true,
        updateRule: (rule: ErrorTrackingBaseRule) => ({ rule }),
        increaseDateRange: true,
    })
}

export function ruleModalReducers<R extends ErrorTrackingBaseRule>(emptyRule: (orderKey?: number) => R): KeaBuilder {
    return reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        rule: [
            emptyRule() as R,
            {
                openModal: (_: R, { rule }: { rule: R | null }) => rule ?? emptyRule(),
                updateRule: (_: R, { rule }: { rule: R }) => rule,
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
    })
}

export function ruleModalLoaders(ruleType: ErrorTrackingRuleType): KeaBuilder {
    return loaders(({ values }: { values: any }) => ({
        matchResult: [
            null as { exceptionCount: number; issueCount: number } | null,
            {
                loadMatchCount: async () => {
                    const filters = values.rule.filters as UniversalFiltersGroup
                    const properties = filters.values as AnyPropertyFilter[]

                    if (properties.length === 0) {
                        return null
                    }

                    const response = (await api.query({
                        kind: NodeKind.EventsQuery,
                        event: '$exception',
                        select: ['count()', 'count(distinct properties.$exception_issue_id)'],
                        properties,
                        after: values.dateRange,
                    })) as Record<string, any>

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
                    await api.errorTracking.deleteRule(ruleType, rule.id)
                    return true
                },
            },
        ],
    }))
}

export function ruleModalListeners(ruleType: ErrorTrackingRuleType): KeaBuilder {
    return listeners(({ actions }: { actions: any }) => ({
        saveRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType }).actions.loadRules()
        },
        deleteRuleSuccess: () => {
            actions.closeModal()
            rulesLogic({ ruleType }).actions.loadRules()
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
    }))
}

export function ruleModalHasFiltersSelector(): KeaBuilder {
    return selectors({
        hasFilters: [
            (s: any) => [s.rule],
            (rule: ErrorTrackingBaseRule): boolean => {
                const filters = rule.filters as UniversalFiltersGroup
                return (filters.values?.length ?? 0) > 0
            },
        ],
    })
}
