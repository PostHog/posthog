import { actions, kea, listeners, path, reducers } from 'kea'

import { insightPickerLogic } from 'lib/components/InsightPicker/insightPickerLogic'

import { QueryBasedInsightModel } from '~/types'

import type { insightPickerEndpointModalLogicType } from './insightPickerEndpointModalLogicType'

export const insightPickerEndpointModalLogic = kea<insightPickerEndpointModalLogicType>([
    path(['products', 'endpoints', 'frontend', 'insightPickerEndpointModalLogic']),
    actions({
        openModal: true,
        closeModal: true,
        selectInsight: (insight: QueryBasedInsightModel) => ({ insight }),
        clearSelectedInsight: true,
        toggleShowMoreInsightTypes: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        selectedInsight: [
            null as QueryBasedInsightModel | null,
            {
                selectInsight: (_, { insight }) => insight,
                clearSelectedInsight: () => null,
                closeModal: () => null,
            },
        ],
        showMoreInsightTypes: [
            false,
            {
                toggleShowMoreInsightTypes: (state) => !state,
                closeModal: () => false,
            },
        ],
    }),
    listeners(() => ({
        closeModal: () => {
            insightPickerLogic({ logicKey: 'endpoints' }).actions.resetFilters()
        },
    })),
])
