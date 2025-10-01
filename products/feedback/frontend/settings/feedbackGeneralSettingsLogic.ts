import { actions, kea, path, reducers } from 'kea'

import { feedbackGeneralSettingsLogicType } from './feedbackGeneralSettingsLogicType'

export const feedbackGeneralSettingsLogic = kea<feedbackGeneralSettingsLogicType>([
    path(['products', 'feedback', 'frontend', 'settings', 'feedbackGeneralSettingsLogic']),

    actions({
        addAvailableFeedbackType: (feedbackType: string) => ({ feedbackType }),
        removeAvailableFeedbackType: (feedbackType: string) => ({ feedbackType }),
    }),

    reducers({
        availableFeedbackTypes: [
            [] as string[],
            {
                persist: true,
            },
            {
                addAvailableFeedbackType: (state, { feedbackType }) => [...state, feedbackType],
                removeAvailableFeedbackType: (state, { feedbackType }) => state.filter((type) => type !== feedbackType),
            },
        ],
    }),
])
