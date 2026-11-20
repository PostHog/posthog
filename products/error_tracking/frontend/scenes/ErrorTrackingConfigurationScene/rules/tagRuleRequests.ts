import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import {
    errorTrackingTagRulesDestroy,
    errorTrackingTagRulesList,
    errorTrackingTagRulesReorderPartialUpdate,
} from '../../../generated/api'
import { ErrorTrackingRule, ErrorTrackingTagRule } from './types'

function projectId(): string {
    return String(teamLogic.values.currentTeamId)
}

export async function listTagRules(): Promise<ErrorTrackingTagRule[]> {
    const { results } = await errorTrackingTagRulesList(projectId())
    return results.map((rule) => ({ ...rule, filters: rule.filters as UniversalFiltersGroup }))
}

export async function destroyTagRule(id: ErrorTrackingRule['id']): Promise<void> {
    return await errorTrackingTagRulesDestroy(projectId(), id)
}

export async function reorderTagRules(orders: Record<string, number>): Promise<void> {
    return await errorTrackingTagRulesReorderPartialUpdate(projectId(), { orders })
}
