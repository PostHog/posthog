import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { FeedbackPreview } from './FeedbackPreview'
import { feedbackGeneralSettingsLogic } from './feedbackGeneralSettingsLogic'

export function FeedbackGeneralSettings(): JSX.Element {
    const { feedbackCategories, feedbackTopics } = useValues(feedbackGeneralSettingsLogic)
    const {
        createFeedbackTopic,
        deleteFeedbackTopic,
        createFeedbackCategory,
        deleteFeedbackCategory,
        createFeedbackStatus,
        deleteFeedbackStatus,
    } = useActions(feedbackGeneralSettingsLogic)

    const [isAddTopicModalOpen, setIsAddTopicModalOpen] = useState(false)
    const [newTopicName, setNewTopicName] = useState('')
    const [isAddCategoryModalOpen, setIsAddCategoryModalOpen] = useState(false)
    const [newCategoryName, setNewCategoryName] = useState('')
    const [isAddStatusModalOpen, setIsAddStatusModalOpen] = useState(false)
    const [newStatusName, setNewStatusName] = useState('')
    const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null)

    const handleAddTopic = (): void => {
        createFeedbackTopic(newTopicName)
        setNewTopicName('')
        setIsAddTopicModalOpen(false)
    }

    const handleAddCategory = (): void => {
        createFeedbackCategory(newCategoryName)
        setNewCategoryName('')
        setIsAddCategoryModalOpen(false)
    }

    const handleAddStatus = (): void => {
        if (selectedCategoryId) {
            createFeedbackStatus(newStatusName, selectedCategoryId)
            setNewStatusName('')
            setIsAddStatusModalOpen(false)
            setSelectedCategoryId(null)
        }
    }

    const openAddStatusModal = (categoryId: string): void => {
        setSelectedCategoryId(categoryId)
        setIsAddStatusModalOpen(true)
    }

    return (
        <div className="space-y-6">
            <div className="border rounded p-4 space-y-6">
                <h2 className="text-xl font-semibold">General Settings</h2>
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
                            {feedbackCategories.map((category) => (
                                <div
                                    key={category.id}
                                    className="group border rounded p-2 bg-surface-primary flex items-center justify-between"
                                >
                                    <div className="font-medium">{category.name}</div>
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="small"
                                        status="danger"
                                        onClick={() => deleteFeedbackCategory(category.id)}
                                        tooltip="Delete category"
                                        className="opacity-0 group-hover:opacity-100 transition-opacity"
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
                            {feedbackTopics.map((topic) => (
                                <div
                                    key={topic.id}
                                    className="group border rounded p-2 bg-surface-primary flex items-center justify-between"
                                >
                                    <div className="font-medium">{topic.name}</div>
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="small"
                                        status="danger"
                                        onClick={() => deleteFeedbackTopic(topic.id)}
                                        tooltip="Delete topic"
                                        className="opacity-0 group-hover:opacity-100 transition-opacity"
                                    />
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="flex flex-col">
                        <h3 className="text-lg font-semibold">Preview</h3>
                        <p className="text-sm text-muted-foreground">This is what your users will see</p>
                        <FeedbackPreview />
                    </div>
                </div>
            </div>

            <div className="border rounded p-4 space-y-4">
                <h2 className="text-xl font-semibold">Category Statuses</h2>
                <p className="text-sm text-muted-foreground">
                    Configure statuses for each category. Statuses help organize feedback items within a category.
                </p>
                <div className="space-y-4">
                    {feedbackCategories.map((category) => (
                        <div key={category.id} className="border rounded p-4 bg-surface-primary space-y-3">
                            <div className="flex items-center justify-between">
                                <h3 className="font-semibold">{category.name}</h3>
                                <LemonButton
                                    type="secondary"
                                    icon={<IconPlus />}
                                    size="small"
                                    onClick={() => openAddStatusModal(category.id)}
                                >
                                    Add Status
                                </LemonButton>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {category.statuses && category.statuses.length > 0 ? (
                                    category.statuses.map((status) => (
                                        <div
                                            key={status.id}
                                            className="group inline-flex items-center gap-2 px-3 py-1.5 bg-surface-tertiary border rounded"
                                        >
                                            <span className="text-sm font-medium">{status.name}</span>
                                            <LemonButton
                                                icon={<IconTrash />}
                                                size="xsmall"
                                                status="danger"
                                                onClick={() => deleteFeedbackStatus(status.id)}
                                                tooltip="Delete status"
                                                className="opacity-0 group-hover:opacity-100 transition-opacity"
                                            />
                                        </div>
                                    ))
                                ) : (
                                    <span className="text-sm text-muted-foreground italic">
                                        No statuses yet. Add one to get started.
                                    </span>
                                )}
                            </div>
                        </div>
                    ))}
                    {feedbackCategories.length === 0 && (
                        <div className="text-sm text-muted-foreground italic text-center py-4">
                            Create categories first to add statuses
                        </div>
                    )}
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
                        placeholder="e.g., Bug, Feature Request, Question"
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

            <LemonModal
                isOpen={isAddStatusModalOpen}
                onClose={() => {
                    setIsAddStatusModalOpen(false)
                    setNewStatusName('')
                    setSelectedCategoryId(null)
                }}
                title="Add Status"
                footer={
                    <>
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                setIsAddStatusModalOpen(false)
                                setNewStatusName('')
                                setSelectedCategoryId(null)
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={handleAddStatus}
                            disabledReason={!newStatusName.trim() ? 'Enter a name' : undefined}
                        >
                            Add
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-2">
                    <p>Enter a name for the new status:</p>
                    <LemonInput
                        value={newStatusName}
                        onChange={setNewStatusName}
                        placeholder="e.g., Open, In Progress, Resolved"
                        autoFocus
                        onPressEnter={handleAddStatus}
                    />
                </div>
            </LemonModal>
        </div>
    )
}
