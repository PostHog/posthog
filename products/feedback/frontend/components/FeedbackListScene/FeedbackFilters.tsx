import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBadge, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { feedbackListSceneLogic } from '../../scenes/FeedbackListScene/feedbackListSceneLogic'
import { feedbackGeneralSettingsLogic } from '../../settings/feedbackGeneralSettingsLogic'

export const FeedbackFilters = (): JSX.Element => {
    const { feedbackCategories, feedbackTopics, feedbackStatuses } = useValues(feedbackGeneralSettingsLogic)

    const { statusFilter, categoryFilter, topicFilter } = useValues(feedbackListSceneLogic)
    const { setStatusFilter, setCategoryFilter, setTopicFilter } = useActions(feedbackListSceneLogic)

    const feedbackTopicsToDisplay = useMemo(() => {
        return [
            { value: 'all', label: 'All topics' },
            ...feedbackTopics.map((topic) => ({
                value: topic.id,
                label: topic.name,
            })),
        ]
    }, [feedbackTopics])

    const feedbackCategoriesToDisplay = useMemo(() => {
        return [
            { value: 'all', label: 'All categories' },
            ...feedbackCategories.map((category) => ({
                value: category.id,
                label: category.name,
            })),
        ]
    }, [feedbackCategories])

    const feedbackStatusesToDisplay = useMemo(() => {
        return [
            { value: 'all', label: 'All statuses' },
            ...feedbackStatuses.map((status) => ({
                value: status.id,
                label: status.name,
            })),
        ]
    }, [feedbackStatuses])

    const statusOption = useMemo(() => {
        if (!statusFilter) {
            return 'all'
        }
        return statusFilter
    }, [statusFilter])

    const categoryOption = useMemo(() => {
        if (!categoryFilter) {
            return 'all'
        }
        return categoryFilter
    }, [categoryFilter])

    const topicOption = useMemo(() => {
        if (!topicFilter) {
            return 'all'
        }
        return topicFilter
    }, [topicFilter])

    return (
        <div className="bg-bg-light border rounded p-4">
            <div className="flex gap-2">
                <LemonInput fullWidth type="search" placeholder="it doesn't do anything (yet)" />
                <LemonSelect
                    value={statusOption}
                    placeholder="Select status"
                    options={feedbackStatusesToDisplay.map((status) => ({
                        value: status.value,
                        label: (
                            <div className="flex items-center gap-2 text-sm">
                                <LemonBadge status="success" size="small" />
                                <span>{status.label}</span>
                            </div>
                        ),
                    }))}
                    size="small"
                    onChange={(status) => {
                        if (status === 'all') {
                            setStatusFilter(null)
                        } else {
                            setStatusFilter(status)
                        }
                    }}
                />
                <LemonSelect
                    value={categoryOption}
                    placeholder="Select category"
                    options={feedbackCategoriesToDisplay.map((category) => ({
                        value: category.value,
                        label: category.label,
                    }))}
                    size="small"
                    onChange={(categoryValue) => {
                        if (categoryValue === 'all') {
                            setCategoryFilter(null)
                        } else {
                            setCategoryFilter(categoryValue)
                        }
                    }}
                />
                <LemonSelect
                    value={topicOption}
                    placeholder="Select topic"
                    options={feedbackTopicsToDisplay.map((topic) => ({
                        value: topic.value,
                        label: topic.label,
                    }))}
                    size="small"
                    onChange={(topicValue) => {
                        if (topicValue === 'all') {
                            setTopicFilter(null)
                        } else {
                            setTopicFilter(topicValue)
                        }
                    }}
                />
            </div>
        </div>
    )
}
