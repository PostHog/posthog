import { JSX } from 'react'

import { IconChat, IconCheckCircle } from '../primitives/icons'
import { getContentText, type ToolViewProps, useToolCallStatus } from '../primitives/toolCallUtils'
import { ToolRow } from './ToolRow'

export function QuestionToolView({ toolCall, turnCancelled, turnComplete }: ToolViewProps): JSX.Element {
    const { status, content, title } = toolCall
    const { isLoading, isComplete, isFailed, wasCancelled } = useToolCallStatus(status, turnCancelled, turnComplete)

    const answerText = getContentText(content)

    if (!isComplete || !answerText) {
        return (
            <ToolRow icon={IconChat} isLoading={isLoading} isFailed={isFailed} wasCancelled={wasCancelled}>
                {title || 'Question'}
            </ToolRow>
        )
    }

    return (
        <div className="my-2 max-w-4xl overflow-hidden rounded-lg border border-border bg-bg-light">
            <div className="flex items-center gap-2 px-3 py-2">
                <IconChat className="text-muted" style={{ fontSize: 12 }} />
                <span className="text-[13px] text-muted">{title || 'Question'}</span>
            </div>

            <div className="border-t border-border px-3 py-2">
                <div className="flex items-center gap-2">
                    <IconCheckCircle className="text-success" style={{ fontSize: 14 }} />
                    <span className="text-[13px] text-success">{answerText}</span>
                </div>
            </div>
        </div>
    )
}
