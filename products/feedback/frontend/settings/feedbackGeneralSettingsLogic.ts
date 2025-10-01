import { actions, events, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { FeedbackItemCategory, FeedbackItemStatus, FeedbackItemTopic } from '../models'
import type { feedbackGeneralSettingsLogicType } from './feedbackGeneralSettingsLogicType'

export const feedbackGeneralSettingsLogic = kea<feedbackGeneralSettingsLogicType>([
    path(['products', 'feedback', 'settings', 'feedbackGeneralSettingsLogic']),

    actions({
        loadFeedbackTopics: true,
        loadFeedbackCategories: true,
        loadFeedbackStatuses: true,
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
        feedbackCategories: [
            [] as FeedbackItemCategory[],
            {
                loadFeedbackCategories: async () => {
                    const response = await api.feedback.categories.list()
                    return response.results
                },
            },
        ],
        feedbackStatuses: [
            [] as FeedbackItemStatus[],
            {
                loadFeedbackStatuses: async () => {
                    const response = await api.feedback.statuses.list()
                    return response.results
                },
            },
        ],
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadFeedbackTopics()
            actions.loadFeedbackCategories()
            actions.loadFeedbackStatuses()
        },
    })),
])
