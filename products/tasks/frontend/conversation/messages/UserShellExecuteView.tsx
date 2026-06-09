import { JSX, memo } from 'react'

import { ToolCallContent } from '../acp-types'
import type { UserShellExecute } from '../buildConversationItems'
import { ExecuteToolView } from '../tools/ExecuteToolView'

export type { UserShellExecute }

interface UserShellExecuteViewProps {
    item: UserShellExecute
}

export const UserShellExecuteView = memo(function UserShellExecuteView({
    item,
}: UserShellExecuteViewProps): JSX.Element {
    const isInProgress = !item.result
    const status = isInProgress ? 'in_progress' : 'completed'
    const output = item.result ? item.result.stdout || item.result.stderr || '' : ''

    const content: ToolCallContent[] = output ? [{ type: 'content', content: { type: 'text', text: output } }] : []

    return (
        <div className="border-l-2 border-accent pl-2">
            <ExecuteToolView
                toolCall={{
                    toolCallId: item.id,
                    title: item.command,
                    kind: 'execute',
                    status,
                    rawInput: { command: item.command, description: '' },
                    content,
                }}
                expanded={true}
            />
        </div>
    )
})
