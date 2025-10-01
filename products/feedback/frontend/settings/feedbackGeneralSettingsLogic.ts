import { actions, events, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { FeedbackItemTopic } from '../models'
import type { feedbackGeneralSettingsLogicType } from './feedbackGeneralSettingsLogicType'

export const DEFAULT_FEEDBACK_CATEGORIES: string[] = ['bug', 'feature', 'improvement']
export const DEFAULT_FEEDBACK_TOPICS: string[] = ['Dashboard', 'Search', 'Export', 'Onboarding']

export const feedbackGeneralSettingsLogic = kea<feedbackGeneralSettingsLogicType>([
    path(['products', 'feedback', 'settings', 'feedbackGeneralSettingsLogic']),

    actions({
        loadFeedbackTopics: true,

        addFeedbackCategory: (key: string) => ({ key }),
        removeFeedbackCategory: (index: number) => ({ index }),
        addFeedbackTopic: (key: string) => ({ key }),
        removeFeedbackTopic: (index: number) => ({ index }),
    }),

    reducers({
        feedbackCategories: [
            DEFAULT_FEEDBACK_CATEGORIES as string[],
            { persist: true },
            {
                addFeedbackCategory: (state, { key }) => [...state, key],
                removeFeedbackCategory: (state, { index }) => state.filter((_, i) => i !== index),
            },
        ],
    }),

    loaders(() => ({
        feedbackTopics: [
            [] as FeedbackItemTopic[],
            {
                loadFeedbackTopics: async () => {
                    const response = await api.feedback.topics.list()

                    return response.results
                },
            },
        ],
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadFeedbackTopics()
        },
    })),
])
