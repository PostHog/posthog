import { actions, kea, path, reducers } from 'kea'

import { HogFunctionSubTemplateIdType } from '~/types'

import type { alertsRecommendationCardLogicType } from './alertsRecommendationCardLogicType'

export const alertsRecommendationCardLogic = kea<alertsRecommendationCardLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingScene',
        'tabs',
        'recommendations',
        'alertsRecommendationCardLogic',
    ]),

    actions({
        openTrigger: (triggerKey: HogFunctionSubTemplateIdType) => ({ triggerKey }),
        closeTrigger: true,
    }),

    reducers({
        openTriggerKey: [
            null as HogFunctionSubTemplateIdType | null,
            {
                openTrigger: (_, { triggerKey }) => triggerKey,
                closeTrigger: () => null,
            },
        ],
    }),
])
