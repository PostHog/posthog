import { JSX } from 'react'

import { IconArrowRightDown } from '../primitives/icons'
import { getFilename, ToolViewProps, useToolCallStatus } from '../primitives/toolCallUtils'
import { ToolRow } from './ToolRow'

export function MoveToolView({ toolCall, turnCancelled, turnComplete }: ToolViewProps): JSX.Element {
    const { status, locations, title } = toolCall
    const { isLoading, isFailed, wasCancelled } = useToolCallStatus(status, turnCancelled, turnComplete)

    const sourcePath = locations?.[0]?.path ?? ''
    const destPath = locations?.[1]?.path ?? ''

    return (
        <ToolRow icon={IconArrowRightDown} isLoading={isLoading} isFailed={isFailed} wasCancelled={wasCancelled}>
            {title ||
                (sourcePath && destPath ? (
                    <>
                        Move <span className="font-mono">{getFilename(sourcePath)}</span> →{' '}
                        <span className="font-mono">{getFilename(destPath)}</span>
                    </>
                ) : (
                    'Move file'
                ))}
        </ToolRow>
    )
}
