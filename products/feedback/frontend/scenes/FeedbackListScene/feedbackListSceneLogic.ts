import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { MOCK_FEEDBACK_ITEMS } from '../../mocks'
import { FeedbackItem, FeedbackStatus, FeedbackType } from '../../types'
import type { feedbackListSceneLogicType } from './feedbackListSceneLogicType'

export const feedbackListSceneLogic = kea<feedbackListSceneLogicType>([
    path(['products', 'feedback', 'scenes', 'FeedbackListScene', 'feedbackListSceneLogic']),

    actions({
        setStatusFilter: (status: FeedbackStatus | null) => ({ status }),
        setTypeFilter: (type: FeedbackType | null) => ({ type }),

        loadFeedbackItems: true,
        openFeedbackItem: (id: string) => ({ id }),
    }),

    reducers({
        statusFilter: [
            null as FeedbackStatus | null,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        typeFilter: [
            null as FeedbackType | null,
            {
                setTypeFilter: (_, { type }) => type,
            },
        ],
    }),

    loaders(({ values }) => ({
        feedbackItems: [
            [] as FeedbackItem[],
            {
                loadFeedbackItems: async () => {
                    await new Promise((resolve) => setTimeout(resolve, 1000))

                    if (!values.statusFilter && !values.typeFilter) {
                        return MOCK_FEEDBACK_ITEMS
                    }

                    if (values.statusFilter && values.typeFilter) {
                        return MOCK_FEEDBACK_ITEMS.filter(
                            (item) => item.status === values.statusFilter && item.type === values.typeFilter
                        )
                    }

                    if (values.statusFilter) {
                        return MOCK_FEEDBACK_ITEMS.filter((item) => item.status === values.statusFilter)
                    }

                    if (values.typeFilter) {
                        return MOCK_FEEDBACK_ITEMS.filter((item) => item.type === values.typeFilter)
                    }

                    return MOCK_FEEDBACK_ITEMS
                },
            },
        ],
    })),

    subscriptions(({ actions }) => ({
        typeFilter: () => {
            return actions.loadFeedbackItems()
        },
        statusFilter: () => {
            return actions.loadFeedbackItems()
        },
    })),

    listeners(() => ({
        openFeedbackItem: ({ id }) => {
            router.actions.push(`/feedback/${id}`)
        },
    })),
])
