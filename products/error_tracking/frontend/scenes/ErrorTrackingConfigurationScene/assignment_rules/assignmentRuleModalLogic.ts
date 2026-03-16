import { kea } from 'kea'

import { FilterLogicalOperator } from '~/types'

import { createRuleModalLogicBuilder } from '../rules/ruleModalLogicFactory'
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
    ...createRuleModalLogicBuilder<ErrorTrackingAssignmentRule>({
        ruleType: ErrorTrackingRuleType.Assignment,
        emptyRule,
        logicPath: [
            'products',
            'error_tracking',
            'scenes',
            'ErrorTrackingConfigurationScene',
            'assignment_rules',
            'assignmentRuleModalLogic',
        ],
        extraSelectors: {
            hasAssignee: [
                (s: any) => [s.rule],
                (rule: ErrorTrackingAssignmentRule): boolean => {
                    return rule.assignee !== null
                },
            ],
        },
    }),
])
