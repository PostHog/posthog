import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { tileCanvasLogic } from './tileCanvasLogic'

export function PlacementHint(): JSX.Element | null {
    const { nodeToBeAdded, isMovingNode, isCopyingNode, isDraggingStep, isDraggingNewStep } = useValues(tileCanvasLogic)
    const { cancel } = useActions(tileCanvasLogic)
    const action = isMovingNode ? 'move the step there' : isCopyingNode ? 'copy the step there' : null
    const verb = isDraggingStep || isDraggingNewStep ? 'Drop on' : 'Click'
    if (!action && !nodeToBeAdded) {
        return null
    }
    return (
        <div className="flex items-center gap-2 rounded-full border bg-surface-primary py-1 pl-3 pr-1 text-sm shadow">
            <span>
                {action ? (
                    <>
                        {verb} a highlighted + to {action}
                    </>
                ) : (
                    <>
                        {verb} a highlighted + to add{' '}
                        <strong>
                            {nodeToBeAdded && 'data' in nodeToBeAdded ? nodeToBeAdded.data.name : nodeToBeAdded?.name}
                        </strong>
                    </>
                )}
            </span>
            <span className="text-secondary">· Esc to cancel</span>
            <LemonButton size="xsmall" icon={<IconX />} tooltip="Cancel" onClick={cancel} />
        </div>
    )
}
