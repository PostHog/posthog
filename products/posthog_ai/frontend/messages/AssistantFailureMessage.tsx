import React from 'react'

import { IconWarning } from '@posthog/icons'
import { ChatBubble, ChatBubbleContent, ChatMessage, ChatMessageContent } from '@posthog/quill-primitives'

import { QuillAssistantMarkdown } from '../components/quill/QuillMessages'
import { useQuillThread } from '../components/quill/quillThreadContext'
import { MarkdownMessage } from './MarkdownMessage'
import { MessageTemplate } from './MessageTemplate'

const DEFAULT_FAILURE_MESSAGE = '*PostHog AI has failed to generate an answer. Please try again.*'

export interface AssistantFailureMessageProps {
    id: string
    content?: string | null
    action?: React.ReactNode
}

export const AssistantFailureMessage = React.forwardRef<HTMLDivElement, AssistantFailureMessageProps>(
    function AssistantFailureMessage({ id, content, action }, ref) {
        const quill = useQuillThread()
        if (quill) {
            return (
                <ChatMessage align="start" ref={ref} data-message-type="ai">
                    <ChatMessageContent className="gap-1">
                        <ChatBubble variant="destructive">
                            <ChatBubbleContent className="flex items-start gap-2">
                                <IconWarning className="mt-1 size-4 shrink-0" />
                                <QuillAssistantMarkdown content={content || DEFAULT_FAILURE_MESSAGE} id={id} />
                            </ChatBubbleContent>
                        </ChatBubble>
                        {action}
                    </ChatMessageContent>
                </ChatMessage>
            )
        }
        return (
            <MessageTemplate type="ai" boxClassName="border-danger" ref={ref} action={action}>
                <MarkdownMessage content={content || DEFAULT_FAILURE_MESSAGE} id={id} />
            </MessageTemplate>
        )
    }
)
