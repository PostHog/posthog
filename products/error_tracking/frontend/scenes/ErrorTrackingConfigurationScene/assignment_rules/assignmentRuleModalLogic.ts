import { kea, path, props, selectors } from 'kea'

import { FilterLogicalOperator } from '~/types'

import {
    ruleModalActions,
    ruleModalHasFiltersSelector,
    ruleModalListeners,
    ruleModalLoaders,
    ruleModalReducers,
} from '../rules/ruleModalLogic'
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
    props({}),
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'assignment_rules',
        'assignmentRuleModalLogic',
    ]),
    ruleModalActions(),
    ruleModalReducers(emptyRule),
    ruleModalLoaders(ErrorTrackingRuleType.Assignment),
    ruleModalListeners(ErrorTrackingRuleType.Assignment),
    ruleModalHasFiltersSelector(),
    selectors({
        hasAssignee: [
            (s) => [s.rule],
            (rule): boolean => {
                return rule.assignee !== null
            },
        ],
    }),
])
