import type { LogicWrapper } from 'kea'

import { FilterLogicalOperator } from '~/types'

import { createRuleModalLogic } from '../rules/ruleModalLogicFactory'
import { ErrorTrackingRuleType, ErrorTrackingSuppressionRule } from '../rules/types'
import type { suppressionRuleModalLogicType } from './suppressionRuleModalLogicType'

function emptyRule(orderKey: number = 0): ErrorTrackingSuppressionRule {
    return {
        id: 'new',
        filters: { type: FilterLogicalOperator.Or, values: [] },
        disabled_data: null,
        order_key: orderKey,
        sampling_rate: 1.0,
    }
}

export const suppressionRuleModalLogic = createRuleModalLogic<ErrorTrackingSuppressionRule>({
    ruleType: ErrorTrackingRuleType.Suppression,
    emptyRule,
    logicPath: [
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'suppression_rules',
        'suppressionRuleModalLogic',
    ],
    allowEmptyFilters: true,
    extraActions: {
        updateSamplingRate: (sampling_rate: number) => ({ sampling_rate }),
    },
    extraRuleReducerHandlers: {
        updateSamplingRate: (state: ErrorTrackingSuppressionRule, { sampling_rate }: { sampling_rate: number }) => ({
            ...state,
            sampling_rate,
        }),
    },
}) as unknown as LogicWrapper<suppressionRuleModalLogicType>
