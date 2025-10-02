import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { FeedbackItemAttachment } from '../../models'
import { feedbackItemSceneLogic } from '../../scenes/FeedbackItemScene/feedbackItemSceneLogic'

export function FeedbackContentTabs(): JSX.Element {
    const [activeTab, setActiveTab] = useState<'attachment' | 'recording'>('attachment')
    const { feedbackItem, feedbackItemLoading } = useValues(feedbackItemSceneLogic)

    if (feedbackItemLoading) {
        return (
            <div className="border rounded-lg p-6 bg-surface">
                <p className="text-muted m-0">Loading</p>
            </div>
        )
    }

    if (!feedbackItem) {
        return (
            <div className="border rounded-lg p-6 bg-surface">
                <p className="text-muted m-0">Feedback item not found</p>
            </div>
        )
    }

    const attachments = feedbackItem?.attachments || []

    return (
        <div className="flex flex-col gap-4 h-full">
            <div className="border rounded-lg overflow-hidden bg-surface">
                <div className="border-b p-4 bg-surface-secondary">
                    <h3 className="text-sm font-semibold m-0">Review Content</h3>
                </div>
                <div className="p-6">
                    <p className="text-sm m-0 whitespace-pre-wrap">{feedbackItem.content}</p>
                </div>
            </div>

            <div className="border rounded-lg overflow-hidden bg-surface flex-1">
                <LemonTabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    barClassName="justify-center"
                    tabs={[
                        {
                            key: 'attachment',
                            label: `Attachment${attachments.length > 0 ? ` (${attachments.length})` : ''}`,
                            content: <AttachmentViewer attachments={attachments} />,
                        },
                        {
                            key: 'recording',
                            label: 'Session Recording',
                            content: (
                                <div className="p-8 flex items-center justify-center text-muted min-h-[200px]">
                                    No related session recording
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </div>
    )
}

function AttachmentViewer({ attachments }: { attachments: FeedbackItemAttachment[] }): JSX.Element {
    const [selectedAttachmentIndex, setSelectedAttachmentIndex] = useState(0)
    const selectedAttachment = attachments[selectedAttachmentIndex]

    if (attachments.length === 0) {
        return (
            <div className="p-8 flex items-center justify-center text-muted min-h-[200px]">No related attachment</div>
        )
    }

    return (
        <div className="flex flex-col h-full">
            <div className="flex items-center justify-center h-[500px]">
                {selectedAttachment?.storage_ptr ? (
                    <img
                        src={selectedAttachment.storage_ptr}
                        alt={`Attachment ${selectedAttachmentIndex + 1}`}
                        className="max-w-full max-h-full object-contain"
                    />
                ) : (
                    <p className="text-muted m-0">Unable to load attachment</p>
                )}
            </div>
            <div className="flex gap-2 flex-wrap bg-surface-secondary p-3 mt-auto">
                {attachments.map((attachment, index) => (
                    <LemonButton
                        key={attachment.id}
                        type={selectedAttachmentIndex === index ? 'primary' : 'secondary'}
                        size="small"
                        onClick={() => setSelectedAttachmentIndex(index)}
                    >
                        Attachment {index + 1}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
