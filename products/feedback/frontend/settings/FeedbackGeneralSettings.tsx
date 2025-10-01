import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { FeedbackPreview } from './FeedbackPreview'
import { feedbackGeneralSettingsLogic } from './feedbackGeneralSettingsLogic'

export function FeedbackGeneralSettings(): JSX.Element {
    const { feedbackCategories, feedbackTopics } = useValues(feedbackGeneralSettingsLogic)
    const { addFeedbackCategory, removeFeedbackCategory, addFeedbackTopic, removeFeedbackTopic } =
        useActions(feedbackGeneralSettingsLogic)

    const [isAddCategoryModalOpen, setIsAddCategoryModalOpen] = useState(false)
    const [isAddTopicModalOpen, setIsAddTopicModalOpen] = useState(false)
    const [newCategoryName, setNewCategoryName] = useState('')
    const [newTopicName, setNewTopicName] = useState('')

    const handleAddCategory = (): void => {
        addFeedbackCategory(newCategoryName)
        setNewCategoryName('')
        setIsAddCategoryModalOpen(false)
    }

    const handleAddTopic = (): void => {
        addFeedbackTopic(newTopicName)
        setNewTopicName('')
        setIsAddTopicModalOpen(false)
    }

    return (
        <div className="space-y-6 border rounded p-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="flex flex-col gap-4">
                    <div className="space-y-2">
                        <div className="flex items-center justify-between">
                            <h3 className="text-lg font-semibold">Feedback categories</h3>
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                size="small"
                                onClick={() => setIsAddCategoryModalOpen(true)}
                            >
                                Add Category
                            </LemonButton>
                        </div>
                        {feedbackCategories.map((category, index) => (
                            <div
                                key={category}
                                className="border rounded p-2 bg-surface-primary flex items-center justify-between"
                            >
                                <div className="font-medium capitalize">{category}</div>
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="xsmall"
                                    status="danger"
                                    onClick={() => removeFeedbackCategory(index)}
                                />
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
                        {feedbackTopics.map((topic, index) => (
                            <div
                                key={topic}
                                className="border rounded p-2 bg-surface-primary flex items-center justify-between"
                            >
                                <div className="font-medium">{topic}</div>
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="xsmall"
                                    status="danger"
                                    onClick={() => removeFeedbackTopic(index)}
                                />
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
                isOpen={isAddCategoryModalOpen}
                onClose={() => {
                    setIsAddCategoryModalOpen(false)
                    setNewCategoryName('')
                }}
                title="Add Feedback Category"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setIsAddCategoryModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={handleAddCategory}
                            disabledReason={!newCategoryName.trim() ? 'Enter a name' : undefined}
                        >
                            Add
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-2">
                    <p>Enter a name for the new feedback category:</p>
                    <LemonInput
                        value={newCategoryName}
                        onChange={setNewCategoryName}
                        placeholder="e.g., question, praise, complaint"
                        autoFocus
                        onPressEnter={handleAddCategory}
                    />
                </div>
            </LemonModal>

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
