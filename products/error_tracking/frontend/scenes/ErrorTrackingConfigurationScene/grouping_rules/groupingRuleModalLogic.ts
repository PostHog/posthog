import type { LogicWrapper } from 'kea'

import { FilterLogicalOperator } from '~/types'

import { createRuleModalLogic } from '../rules/ruleModalLogicFactory'
import { ErrorTrackingGroupingRule, ErrorTrackingRuleType } from '../rules/types'
import type { groupingRuleModalLogicType } from './groupingRuleModalLogicType'

function emptyRule(orderKey: number = 0): ErrorTrackingGroupingRule {
    return {
        id: 'new',
        filters: { type: FilterLogicalOperator.And, values: [] },
        assignee: null,
        disabled_data: null,
        order_key: orderKey,
    }
}

export const groupingRuleModalLogic = createRuleModalLogic<ErrorTrackingGroupingRule>({
    ruleType: ErrorTrackingRuleType.Grouping,
    emptyRule,
    logicPath: [
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'grouping_rules',
        'groupingRuleModalLogic',
    ],
}) as unknown as LogicWrapper<groupingRuleModalLogicType>
