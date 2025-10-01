import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { FeedbackPreview } from './FeedbackPreview'
import { feedbackGeneralSettingsLogic } from './feedbackGeneralSettingsLogic'

export function FeedbackGeneralSettings(): JSX.Element {
    const { feedbackCategories, feedbackTopics, feedbackStatuses } = useValues(feedbackGeneralSettingsLogic)
    const { createFeedbackTopic } = useActions(feedbackGeneralSettingsLogic)

    const [isAddTopicModalOpen, setIsAddTopicModalOpen] = useState(false)
    const [newTopicName, setNewTopicName] = useState('')

    const handleAddTopic = (): void => {
        createFeedbackTopic(newTopicName)
        setNewTopicName('')
        setIsAddTopicModalOpen(false)
    }

    return (
        <div className="space-y-6 border rounded p-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="flex flex-col gap-4">
                    <div className="space-y-2">
                        <h3 className="text-lg font-semibold">Feedback categories</h3>
                        {feedbackCategories.map((category) => (
                            <div key={category.id} className="border rounded p-2 bg-surface-primary">
                                <div className="font-medium">{category.name}</div>
                            </div>
                        ))}
                    </div>

                    <div className="space-y-2">
                        <div className="flex items-center justify-between">
                            <h3 className="text-lg font-semibold">Feedback topics</h3>
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                size="small"
                                onClick={() => setIsAddTopicModalOpen(true)}
                            >
                                Add Topic
                            </LemonButton>
                        </div>
                        {feedbackTopics.map((topic) => (
                            <div key={topic.id} className="border rounded p-2 bg-surface-primary">
                                <div className="font-medium">{topic.name}</div>
                            </div>
                        ))}
                    </div>

                    <div className="space-y-2">
                        <h3 className="text-lg font-semibold">Feedback statuses</h3>
                        {feedbackStatuses.map((status) => (
                            <div key={status.id} className="border rounded p-2 bg-surface-primary">
                                <div className="font-medium">{status.name}</div>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="flex flex-col gap-0">
                    <h3 className="text-lg font-semibold">Preview</h3>
                    <p className="text-sm text-muted-foreground">This is what your users will see</p>
                    <FeedbackPreview />
                </div>
            </div>

            <LemonModal
                isOpen={isAddTopicModalOpen}
                onClose={() => {
                    setIsAddTopicModalOpen(false)
                    setNewTopicName('')
                }}
                title="Add Feedback Topic"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setIsAddTopicModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={handleAddTopic}
                            disabledReason={!newTopicName.trim() ? 'Enter a name' : undefined}
                        >
                            Add
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-2">
                    <p>Enter a name for the new feedback topic:</p>
                    <LemonInput
                        value={newTopicName}
                        onChange={setNewTopicName}
                        placeholder="e.g., Dashboard, Reports, Settings"
                        autoFocus
                        onPressEnter={handleAddTopic}
                    />
                </div>
            </LemonModal>
        </div>
    )
}
