import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { dayjs } from 'lib/dayjs'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { FeedbackItem } from '../../models'
import { feedbackListSceneLogic } from '../../scenes/FeedbackListScene/feedbackListSceneLogic'
import { feedbackGeneralSettingsLogic } from '../../settings/feedbackGeneralSettingsLogic'

export function FeedbackList(): JSX.Element {
    const { feedbackItems, feedbackItemsLoading } = useValues(feedbackListSceneLogic)
    const { openFeedbackItem, updateStatus, updateAssignment, updateCategory } = useActions(feedbackListSceneLogic)
    const { feedbackCategories, getStatusesForCategory } = useValues(feedbackGeneralSettingsLogic)

    const columns: LemonTableColumns<FeedbackItem> = [
        {
            title: 'Feedback',
            key: 'content',
            render: (_, feedback) => (
                <div className="flex-1 min-w-0 p-1">
                    <p className="font-medium mb-0">{feedback.content}</p>
                    <div className="flex items-center gap-1.5 text-muted text-xs mt-1">
                        <span>Opened {dayjs(feedback.created_at).fromNow()}</span>
                        <span>·</span>
                        <span>todo@todo.com</span>
                    </div>
                </div>
            ),
        },
        {
            title: 'Category',
            key: 'category',
            width: 200,
            render: (_, feedback) => (
                <LemonSelect
                    fullWidth
                    value={feedback.category?.id}
                    onChange={(value) => value && updateCategory(feedback.id, value)}
                    options={feedbackCategories.map((category) => ({
                        label: category.name,
                        value: category.id,
                    }))}
                    size="small"
                    onClick={(e) => e.stopPropagation()}
                />
            ),
        },
        {
            title: 'Status',
            key: 'status',
            width: 200,
            render: (_, feedback) => {
                const availableStatuses = feedback.category?.id ? getStatusesForCategory(feedback.category.id) : []
                return (
                    <LemonSelect
                        fullWidth
                        value={feedback.status?.id}
                        onChange={(value) => value && updateStatus(feedback.id, value)}
                        options={availableStatuses.map((status) => ({
                            label: status.name,
                            value: status.id,
                        }))}
                        size="small"
                        onClick={(e) => e.stopPropagation()}
                        placeholder="Select status"
                    />
                )
            },
        },
        {
            title: 'Assigned to',
            key: 'assignment',
            width: 200,
            render: (_, feedback) => (
                <div onClick={(e) => e.stopPropagation()}>
                    <MemberSelect
                        value={feedback.assignment?.user?.id ?? null}
                        onChange={(user) => updateAssignment(feedback.id, user?.id ?? null)}
                        defaultLabel="Unassigned"
                        allowNone={true}
                        type="secondary"
                        size="small"
                    />
                </div>
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={feedbackItems}
            columns={columns}
            loading={feedbackItemsLoading}
            rowKey="id"
            nouns={['feedback item', 'feedback items']}
            emptyState="No feedback items found"
            onRow={(feedback) => ({
                onClick: () => openFeedbackItem(feedback.id),
            })}
        />
    )
}
