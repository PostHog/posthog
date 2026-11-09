import { useDndMonitor, useDraggable } from '@dnd-kit/core'
import { HTMLAttributes, ReactNode } from 'react'

import { IconDrag } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { WORKFLOW_FILES_DRAG_SCOPE } from './workflowFolderDragScopes'

type WorkflowFolderRowProps = {
    icon: JSX.Element
    drag?: { id: string; label: string }
    children: ReactNode
} & Omit<HTMLAttributes<HTMLDivElement>, 'className'>

export function WorkflowFolderRow({ icon, drag, children, ...props }: WorkflowFolderRowProps): JSX.Element {
    if (drag) {
        return (
            <DraggableRow icon={icon} drag={drag} {...props}>
                {children}
            </DraggableRow>
        )
    }
    return (
        <div className="flex items-center gap-2 min-w-0" {...props}>
            <span className="flex size-6 shrink-0 items-center justify-center text-secondary">{icon}</span>
            {children}
        </div>
    )
}

function DraggableRow({
    icon,
    drag,
    children,
    ...props
}: WorkflowFolderRowProps & { drag: { id: string; label: string } }): JSX.Element {
    const id = `${WORKFLOW_FILES_DRAG_SCOPE}::${drag.id}`
    const { listeners, setNodeRef } = useDraggable({
        id,
        data: { treeId: drag.id, treeScope: WORKFLOW_FILES_DRAG_SCOPE },
    })
    const ignoreClickAfterDrop = ({ active }: { active: { id: string | number } }): void => {
        if (active.id === id) {
            ignoreNextClick()
        }
    }
    useDndMonitor({ onDragEnd: ignoreClickAfterDrop, onDragCancel: ignoreClickAfterDrop })
    return (
        <div ref={setNodeRef} className="flex items-center gap-2 min-w-0 cursor-grab" {...props} {...listeners}>
            <span className="relative flex size-6 shrink-0 items-center justify-center text-secondary">
                <span className="flex group-hover/row:opacity-0 group-focus-within/row:opacity-0">{icon}</span>
                <span className="absolute inset-0 opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100">
                    <LemonButton size="xsmall" icon={<IconDrag />} aria-label={drag.label} />
                </span>
            </span>
            {children}
        </div>
    )
}

// A drop released over the row's own link would otherwise follow it.
function ignoreNextClick(): void {
    const ignore = (event: MouseEvent): void => event.preventDefault()
    window.addEventListener('click', ignore, { capture: true, once: true })
    setTimeout(() => window.removeEventListener('click', ignore, { capture: true }), 50)
}
