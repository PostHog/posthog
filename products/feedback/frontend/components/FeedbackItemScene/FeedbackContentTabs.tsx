import { useActions, useValues } from 'kea'

import { IconLogomark } from '@posthog/icons'
import { LemonCard, LemonDivider } from '@posthog/lemon-ui'

import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'

import { FeedbackItemAttachment } from '../../models'
import { feedbackItemSceneLogic } from '../../scenes/FeedbackItemScene/feedbackItemSceneLogic'
import { feedbackContentTabsLogic } from './feedbackContentTabsLogic'

export function FeedbackContentTabs(): JSX.Element {
    const { feedbackItem, feedbackItemLoading } = useValues(feedbackItemSceneLogic)
    const { currentTab } = useValues(feedbackContentTabsLogic)
    const { setCurrentTab } = useActions(feedbackContentTabsLogic)

    const handleTabChange = (value: string): void => {
        if (value === 'attachments' || value === 'recording') {
            setCurrentTab(value)
        }
    }

    if (!feedbackItem && !feedbackItemLoading) {
        return (
            <div className="border rounded-lg p-6 bg-surface">
                <p className="text-muted m-0">Feedback item not found</p>
            </div>
        )
    }

    const attachments = feedbackItem?.attachments || []

    return (
        <div className="flex flex-col gap-2">
            <LemonCard hoverEffect={false} className="p-4">
                <p className="text-sm m-0 whitespace-pre-wrap">{feedbackItem?.content}</p>
            </LemonCard>

            <LemonCard hoverEffect={false} className="p-0 relative overflow-hidden">
                <TabsPrimitive value={currentTab} onValueChange={handleTabChange}>
                    <div className="flex justify-between h-[2rem] items-center w-full px-2 border-b">
                        <TabsPrimitiveList className="flex justify-between w-full h-full items-center">
                            <div className="w-full h-full">
                                <div className="flex items-center gap-1 text-lg h-full">
                                    <IconLogomark />
                                    <span className="text-sm">Context</span>
                                </div>
                            </div>
                            <div className="flex gap-2 w-full justify-center h-full">
                                <TabsPrimitiveTrigger className="px-2" value="attachments">
                                    Attachments{attachments.length > 0 ? ` (${attachments.length})` : ''}
                                </TabsPrimitiveTrigger>
                                <TabsPrimitiveTrigger className="px-2" value="recording">
                                    Session Recording
                                </TabsPrimitiveTrigger>
                            </div>
                            <div className="w-full flex gap-2 justify-end items-center" />
                        </TabsPrimitiveList>
                    </div>
                    <TabsPrimitiveContent value="attachments">
                        <AttachmentViewer attachments={attachments} />
                    </TabsPrimitiveContent>
                    <TabsPrimitiveContent value="recording">
                        <div className="p-8 flex items-center justify-center text-muted min-h-[300px]">
                            No related session recording
                        </div>
                    </TabsPrimitiveContent>
                </TabsPrimitive>
            </LemonCard>
        </div>
    )
}

function AttachmentViewer({ attachments }: { attachments: FeedbackItemAttachment[] }): JSX.Element {
    const { selectedAttachmentIndex } = useValues(feedbackContentTabsLogic)
    const { setSelectedAttachmentIndex } = useActions(feedbackContentTabsLogic)
    const selectedAttachment = attachments[selectedAttachmentIndex]

    if (attachments.length === 0) {
        return (
            <div className="p-8 flex items-center justify-center text-muted min-h-[300px]">No related attachment</div>
        )
    }

    return (
        <div className="flex flex-col h-full">
            <div className="flex items-center justify-center min-h-[400px] bg-surface-secondary">
                {selectedAttachment?.storage_ptr ? (
                    <img
                        src={selectedAttachment.storage_ptr}
                        alt={`Attachment ${selectedAttachmentIndex + 1}`}
                        className="max-w-full max-h-[400px] object-contain"
                    />
                ) : (
                    <p className="text-muted m-0">Unable to load attachment</p>
                )}
            </div>
            <LemonDivider className="mb-0" />
            <div className="flex gap-2 flex-wrap bg-white p-3 mt-auto">
                {attachments.map((attachment, index) => (
                    <button
                        key={attachment.id}
                        onClick={() => setSelectedAttachmentIndex(index)}
                        className={`
                            relative overflow-hidden rounded border-2
                            ${selectedAttachmentIndex === index ? 'border-primary' : 'border-transparent hover:border-accent-muted'}
                        `}
                    >
                        {attachment.storage_ptr && (
                            <img
                                src={attachment.storage_ptr}
                                alt={`Thumbnail ${index + 1}`}
                                className="w-16 h-16 object-cover"
                            />
                        )}
                    </button>
                ))}
            </div>
        </div>
    )
}
