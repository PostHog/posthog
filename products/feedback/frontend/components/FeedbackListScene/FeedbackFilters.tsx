import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBadge, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { feedbackListSceneLogic } from '../../scenes/FeedbackListScene/feedbackListSceneLogic'
import { feedbackGeneralSettingsLogic } from '../../settings/feedbackGeneralSettingsLogic'
import { FeedbackStatus, StatusOption } from '../../types'

const STATUS_LABELS: Record<StatusOption, { label: string; color: 'success' | 'warning' | 'muted' }> = {
    all: { label: 'All statuses', color: 'muted' },
    [FeedbackStatus.Visible]: { label: 'Visible', color: 'success' },
    [FeedbackStatus.Hidden]: { label: 'Hidden', color: 'warning' },
}

export const FeedbackFilters = (): JSX.Element => {
    const { feedbackCategories, feedbackTopics } = useValues(feedbackGeneralSettingsLogic)
    const statusOptions: StatusOption[] = ['all', FeedbackStatus.Visible, FeedbackStatus.Hidden]
    const categoryOptions: Array<string | 'all'> = ['all', ...feedbackCategories]
    const topicOptions: Array<string | 'all'> = ['all', ...feedbackTopics]

    const { statusFilter, categoryFilter, topicFilter } = useValues(feedbackListSceneLogic)
    const { setStatusFilter, setCategoryFilter, setTopicFilter } = useActions(feedbackListSceneLogic)

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
                    options={statusOptions.map((status) => ({
                        value: status,
                        label: (
                            <div className="flex items-center gap-2 text-sm">
                                <LemonBadge status={STATUS_LABELS[status].color} size="small" />
                                <span>{STATUS_LABELS[status].label}</span>
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
                    options={categoryOptions.map((category) => ({
                        value: category,
                        label: category === 'all' ? 'All categories' : category,
                    }))}
                    size="small"
                    onChange={(category) => {
                        if (category === 'all') {
                            setCategoryFilter(null)
                        } else {
                            setCategoryFilter(category)
                        }
                    }}
                />
                <LemonSelect
                    value={topicOption}
                    placeholder="Select topic"
                    options={topicOptions.map((topic) => ({
                        value: topic,
                        label: topic === 'all' ? 'All topics' : topic,
                    }))}
                    size="small"
                    onChange={(topic) => {
                        if (topic === 'all') {
                            setTopicFilter(null)
                        } else {
                            setTopicFilter(topic)
                        }
                    }}
                />
            </div>
        </div>
    )
}
