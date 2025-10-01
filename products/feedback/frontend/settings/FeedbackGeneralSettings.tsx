import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { FeedbackPreview } from './FeedbackPreview'
import { feedbackGeneralSettingsLogic } from './feedbackGeneralSettingsLogic'

export function FeedbackGeneralSettings(): JSX.Element {
    const { feedbackTypes } = useValues(feedbackGeneralSettingsLogic)
    const { addFeedbackType, removeFeedbackType } = useActions(feedbackGeneralSettingsLogic)

    const [isAddModalOpen, setIsAddModalOpen] = useState(false)
    const [newTypeName, setNewTypeName] = useState('')

    const handleAdd = (): void => {
        addFeedbackType(newTypeName)
        setNewTypeName('')
        setIsAddModalOpen(false)
    }

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="flex flex-col gap-4">
                    <div className="flex items-center justify-between">
                        <h3 className="text-lg font-semibold">Feedback Types</h3>
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            size="small"
                            onClick={() => setIsAddModalOpen(true)}
                        >
                            Add Type
                        </LemonButton>
                    </div>

                    <div className="space-y-2">
                        {feedbackTypes.map((type, index) => (
                            <div
                                key={type}
                                className="border rounded p-2 bg-surface-primary flex items-center justify-between"
                            >
                                <div className="font-medium capitalize">{type}</div>
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="xsmall"
                                    status="danger"
                                    onClick={() => removeFeedbackType(index)}
                                />
                            </div>
                        ))}
                    </div>
                </div>

                <div className="flex flex-col gap-4">
                    <h3 className="text-lg font-semibold">Preview</h3>
                    <FeedbackPreview feedbackTypes={feedbackTypes} />
                </div>
            </div>

            <LemonModal
                isOpen={isAddModalOpen}
                onClose={() => {
                    setIsAddModalOpen(false)
                    setNewTypeName('')
                }}
                title="Add Feedback Type"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setIsAddModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={handleAdd}
                            disabledReason={!newTypeName.trim() ? 'Enter a name' : undefined}
                        >
                            Add
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-2">
                    <p>Enter a name for the new feedback type:</p>
                    <LemonInput
                        value={newTypeName}
                        onChange={setNewTypeName}
                        placeholder="e.g., question, praise, complaint"
                        autoFocus
                        onPressEnter={handleAdd}
                    />
                </div>
            </LemonModal>
        </div>
    )
}
