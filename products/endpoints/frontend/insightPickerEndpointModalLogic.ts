import { actions, kea, listeners, path, reducers } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'

import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { urls } from 'scenes/urls'

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
            addSavedInsightsModalLogic.findMounted()?.actions.setModalFilters({}, false)
        },
    })),
    actionToUrl(() => ({
        openModal: () => [urls.endpoints(), { new: 'insight' }],
        closeModal: () => [urls.endpoints(), {}],
    })),
    urlToAction(({ actions, values }) => ({
        [urls.endpoints()]: (_, searchParams) => {
            if (searchParams.new === 'insight' && !values.isOpen) {
                actions.openModal()
            } else if (searchParams.new !== 'insight' && values.isOpen) {
                actions.closeModal()
            }
        },
    })),
])
