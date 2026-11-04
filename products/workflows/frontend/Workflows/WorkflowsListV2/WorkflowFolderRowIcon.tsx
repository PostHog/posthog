import { IconDrag } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TreeNodeDraggable } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { cn } from 'lib/utils/css-classes'

import { WORKFLOW_FILES_DRAG_SCOPE } from './workflowFolderDragScopes'

export function WorkflowFolderRowIcon({
    icon,
    drag,
}: {
    icon: JSX.Element
    drag?: { id: string; label: string }
}): JSX.Element {
    return (
        <span className="relative flex size-6 shrink-0 items-center justify-center text-secondary">
            <span className={cn('flex', drag && 'group-hover/row:opacity-0 group-focus-within/row:opacity-0')}>
                {icon}
            </span>
            {drag && (
                <TreeNodeDraggable
                    id={drag.id}
                    scope={WORKFLOW_FILES_DRAG_SCOPE}
                    enableDragging
                    className="absolute inset-0 opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100"
                >
                    <LemonButton size="xsmall" icon={<IconDrag />} aria-label={drag.label} />
                </TreeNodeDraggable>
            )}
        </span>
    )
}
