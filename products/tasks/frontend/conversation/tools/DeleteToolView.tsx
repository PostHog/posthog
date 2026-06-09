import { JSX } from 'react'

import { FileMentionChip } from '../primitives/FileMentionChip'
import { IconTrash } from '../primitives/icons'
import {
    type DiffContent,
    findDiffContent,
    LoadingIcon,
    StatusIndicators,
    type ToolViewProps,
    useToolCallStatus,
} from '../primitives/toolCallUtils'

function getDeletedLineCount(diff: DiffContent | undefined): number | null {
    if (!diff?.oldText) {
        return null
    }
    return diff.oldText.split('\n').length
}

export function DeleteToolView({ toolCall, turnCancelled, turnComplete }: ToolViewProps): JSX.Element {
    const { status, locations, content } = toolCall
    const { isLoading, isFailed, wasCancelled } = useToolCallStatus(status, turnCancelled, turnComplete)

    const filePath = locations?.[0]?.path ?? ''
    const diff = findDiffContent(content)
    const deletedLines = getDeletedLineCount(diff)

    return (
        <div className="max-w-4xl overflow-hidden rounded-lg border border-border">
            <div className="flex items-center gap-2 px-3 py-2">
                <LoadingIcon icon={IconTrash} isLoading={isLoading} />
                {filePath && <FileMentionChip path={filePath} />}
                {deletedLines !== null && (
                    <span className="font-mono text-[13px]">
                        <span className="text-danger">-{deletedLines}</span>
                    </span>
                )}
                <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
            </div>
        </div>
    )
}
