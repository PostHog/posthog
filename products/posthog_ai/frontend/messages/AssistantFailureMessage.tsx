import React from 'react'

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
        return (
            <MessageTemplate type="ai" boxClassName="border-danger" ref={ref} action={action}>
                <MarkdownMessage content={content || DEFAULT_FAILURE_MESSAGE} id={id} />
            </MessageTemplate>
        )
    }
)
