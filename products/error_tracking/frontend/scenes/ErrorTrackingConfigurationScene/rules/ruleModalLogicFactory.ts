import { actions, kea as keaBuild, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, UniversalFiltersGroup } from '~/types'

import { rulesLogic } from './rulesLogic'
import { ErrorTrackingBaseRule, ErrorTrackingRuleType } from './types'

export interface RuleModalLogicFactoryOptions<T extends ErrorTrackingBaseRule> {
    ruleType: ErrorTrackingRuleType
    emptyRule: (orderKey?: number) => T
    logicPath: string[]
    /** If true, loadMatchCount runs even with no filters (for suppression rules). Default: false */
    allowEmptyFilters?: boolean
    /** Extra actions beyond the shared ones */
    extraActions?: Record<string, any>
    /** Extra reducer handlers for the `rule` reducer, merged at build time */
    extraRuleReducerHandlers?: Record<string, (...args: any[]) => T>
    /** Extra selectors */
    extraSelectors?: Record<string, any>
}

/**
 * Creates a kea logic for a rule modal. The `kea` import is aliased to `keaBuild`
 * to prevent kea-typegen from processing this factory (which causes an infinite loop).
 * Consumer type files are manually maintained.
 */
// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
export function createRuleModalLogic<T extends ErrorTrackingBaseRule>(options: RuleModalLogicFactoryOptions<T>) {
    const {
        ruleType,
        emptyRule,
        logicPath,
        allowEmptyFilters = false,
        extraActions,
        extraRuleReducerHandlers,
        extraSelectors,
    } = options

    return keaBuild([
        props({}),
        path(logicPath),

        actions({
            openModal: (rule?: T) => ({ rule: rule ?? null }),
            closeModal: true,
            updateRule: (rule: T) => ({ rule }),
            increaseDateRange: true,
            ...extraActions,
        } as any),

        reducers({
            isOpen: [false, { openModal: () => true, closeModal: () => false }],
            rule: [
                emptyRule() as T,
                Object.assign(
                    {
                        openModal: (_: T, { rule }: { rule: T | null }) => rule ?? emptyRule(),
                        updateRule: (_: T, { rule }: { rule: T }) => rule,
                    },
                    extraRuleReducerHandlers ?? {}
                ),
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
                            query.properties = properties
                        } else if (!allowEmptyFilters) {
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
        })),

        listeners(({ actions }) => ({
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
        })),

        selectors({
            hasFilters: [
                (s) => [s.rule],
                (rule: T): boolean => {
                    const filters = rule.filters as UniversalFiltersGroup
                    return (filters.values?.length ?? 0) > 0
                },
            ],
            ...extraSelectors,
        }),
    ])
}
