import { kea, path, props } from 'kea'

import { FilterLogicalOperator } from '~/types'

import {
    ruleModalActions,
    ruleModalHasFiltersSelector,
    ruleModalListeners,
    ruleModalLoaders,
    ruleModalReducers,
} from '../rules/ruleModalLogic'
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

export const groupingRuleModalLogic = kea<groupingRuleModalLogicType>([
    props({}),
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'grouping_rules',
        'groupingRuleModalLogic',
    ]),
    ruleModalActions(),
    ruleModalReducers(emptyRule),
    ruleModalLoaders(ErrorTrackingRuleType.Grouping),
    ruleModalListeners(ErrorTrackingRuleType.Grouping),
    ruleModalHasFiltersSelector(),
])
