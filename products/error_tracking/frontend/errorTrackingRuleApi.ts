import { ApiConfig } from 'lib/api'

import {
    errorTrackingAssignmentRulesCreate,
    errorTrackingAssignmentRulesDestroy,
    errorTrackingAssignmentRulesList,
    errorTrackingAssignmentRulesPartialUpdate,
    errorTrackingAssignmentRulesReorderPartialUpdate,
    errorTrackingBypassRulesCreate,
    errorTrackingBypassRulesDestroy,
    errorTrackingBypassRulesList,
    errorTrackingBypassRulesPartialUpdate,
    errorTrackingBypassRulesReorderPartialUpdate,
    errorTrackingGroupingRulesCreate,
    errorTrackingGroupingRulesDestroy,
    errorTrackingGroupingRulesList,
    errorTrackingGroupingRulesPartialUpdate,
    errorTrackingGroupingRulesReorderPartialUpdate,
    errorTrackingSuppressionRulesCreate,
    errorTrackingSuppressionRulesDestroy,
    errorTrackingSuppressionRulesList,
    errorTrackingSuppressionRulesPartialUpdate,
    errorTrackingSuppressionRulesReorderPartialUpdate,
} from './generated/api'
import type { ErrorTrackingRule, ErrorTrackingRuleType } from './scenes/ErrorTrackingConfigurationScene/rules/types'

// nosemgrep: prefer-codegen-api
const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export async function errorTrackingRulesList(
    ruleType: ErrorTrackingRuleType
): Promise<{ results: ErrorTrackingRule[] }> {
    switch (ruleType) {
        case 'assignment_rules':
            return (await errorTrackingAssignmentRulesList(projectId())) as { results: ErrorTrackingRule[] }
        case 'bypass_rules':
            return (await errorTrackingBypassRulesList(projectId())) as { results: ErrorTrackingRule[] }
        case 'grouping_rules':
            return (await errorTrackingGroupingRulesList(projectId())) as { results: ErrorTrackingRule[] }
        case 'suppression_rules':
            return (await errorTrackingSuppressionRulesList(projectId())) as { results: ErrorTrackingRule[] }
        default:
            throw new Error(`Unsupported error tracking rule type: ${ruleType}`)
    }
}

export async function errorTrackingRulesCreate(
    ruleType: ErrorTrackingRuleType,
    rule: ErrorTrackingRule
): Promise<ErrorTrackingRule> {
    const { id: _, ...data } = rule
    switch (ruleType) {
        case 'assignment_rules':
            return (await errorTrackingAssignmentRulesCreate(
                projectId(),
                data as Parameters<typeof errorTrackingAssignmentRulesCreate>[1]
            )) as unknown as ErrorTrackingRule
        case 'bypass_rules':
            return (await errorTrackingBypassRulesCreate(
                projectId(),
                data as Parameters<typeof errorTrackingBypassRulesCreate>[1]
            )) as unknown as ErrorTrackingRule
        case 'grouping_rules':
            return (await errorTrackingGroupingRulesCreate(
                projectId(),
                data as Parameters<typeof errorTrackingGroupingRulesCreate>[1]
            )) as unknown as ErrorTrackingRule
        case 'suppression_rules':
            return (await errorTrackingSuppressionRulesCreate(
                projectId(),
                data as Parameters<typeof errorTrackingSuppressionRulesCreate>[1]
            )) as unknown as ErrorTrackingRule
        default:
            throw new Error(`Unsupported error tracking rule type: ${ruleType}`)
    }
}

export async function errorTrackingRulesUpdate(
    ruleType: ErrorTrackingRuleType,
    rule: ErrorTrackingRule
): Promise<void> {
    const { id, ...data } = rule
    switch (ruleType) {
        case 'assignment_rules':
            await errorTrackingAssignmentRulesPartialUpdate(
                projectId(),
                id,
                data as Parameters<typeof errorTrackingAssignmentRulesPartialUpdate>[2]
            )
            return
        case 'bypass_rules':
            await errorTrackingBypassRulesPartialUpdate(
                projectId(),
                id,
                data as Parameters<typeof errorTrackingBypassRulesPartialUpdate>[2]
            )
            return
        case 'grouping_rules':
            await errorTrackingGroupingRulesPartialUpdate(
                projectId(),
                id,
                data as Parameters<typeof errorTrackingGroupingRulesPartialUpdate>[2]
            )
            return
        case 'suppression_rules':
            await errorTrackingSuppressionRulesPartialUpdate(
                projectId(),
                id,
                data as Parameters<typeof errorTrackingSuppressionRulesPartialUpdate>[2]
            )
    }
}

export async function errorTrackingRulesDestroy(ruleType: ErrorTrackingRuleType, id: string): Promise<void> {
    const destroy = {
        assignment_rules: errorTrackingAssignmentRulesDestroy,
        bypass_rules: errorTrackingBypassRulesDestroy,
        grouping_rules: errorTrackingGroupingRulesDestroy,
        suppression_rules: errorTrackingSuppressionRulesDestroy,
    }[ruleType]
    await destroy(projectId(), id)
}

export async function errorTrackingRulesReorder(
    ruleType: ErrorTrackingRuleType,
    orders: Record<string, number>
): Promise<void> {
    const reorder = {
        assignment_rules: errorTrackingAssignmentRulesReorderPartialUpdate,
        bypass_rules: errorTrackingBypassRulesReorderPartialUpdate,
        grouping_rules: errorTrackingGroupingRulesReorderPartialUpdate,
        suppression_rules: errorTrackingSuppressionRulesReorderPartialUpdate,
    }[ruleType]
    await reorder(projectId(), { orders } as never)
}
