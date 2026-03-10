import { kea, path, props } from 'kea'

import { FilterLogicalOperator } from '~/types'

import {
    ruleModalActions,
    ruleModalHasFiltersSelector,
    ruleModalListeners,
    ruleModalLoaders,
    ruleModalReducers,
} from '../rules/ruleModalLogic'
import { ErrorTrackingRuleType, ErrorTrackingSuppressionRule } from '../rules/types'
import type { suppressionRuleModalLogicType } from './suppressionRuleModalLogicType'

function emptyRule(orderKey: number = 0): ErrorTrackingSuppressionRule {
    return {
        id: 'new',
        filters: { type: FilterLogicalOperator.Or, values: [] },
        disabled_data: null,
        order_key: orderKey,
    }
}

export const suppressionRuleModalLogic = kea<suppressionRuleModalLogicType>([
    props({}),
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'suppression_rules',
        'suppressionRuleModalLogic',
    ]),
    ruleModalActions(),
    ruleModalReducers(emptyRule),
    ruleModalLoaders(ErrorTrackingRuleType.Suppression),
    ruleModalListeners(ErrorTrackingRuleType.Suppression),
    ruleModalHasFiltersSelector(),
])
