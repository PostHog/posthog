import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import {
    errorTrackingTagRulesDestroy,
    errorTrackingTagRulesList,
    errorTrackingTagRulesReorderPartialUpdate,
} from '../../../generated/api'
import { ErrorTrackingRule, ErrorTrackingRuleType } from './types'

function projectId(): string {
    return String(teamLogic.values.currentTeamId)
}

export async function listRules(ruleType: ErrorTrackingRuleType): Promise<ErrorTrackingRule[]> {
    if (ruleType === ErrorTrackingRuleType.Tag) {
        const { results } = await errorTrackingTagRulesList(projectId())
        return results.map((rule) => ({ ...rule, filters: rule.filters as UniversalFiltersGroup }))
    }
    const { results } = await api.errorTracking.rules(ruleType)
    return results
}

export async function destroyRule(ruleType: ErrorTrackingRuleType, id: ErrorTrackingRule['id']): Promise<void> {
    if (ruleType === ErrorTrackingRuleType.Tag) {
        return await errorTrackingTagRulesDestroy(projectId(), id)
    }
    return await api.errorTracking.deleteRule(ruleType, id)
}

export async function reorderRules(ruleType: ErrorTrackingRuleType, orders: Record<string, number>): Promise<void> {
    if (ruleType === ErrorTrackingRuleType.Tag) {
        return await errorTrackingTagRulesReorderPartialUpdate(projectId(), { orders })
    }
    return await api.errorTracking.reorderRules(ruleType, orders)
}
