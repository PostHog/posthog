import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { PropsWithChildren } from 'react'

import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { ErrorTrackingRule } from './types'

export function SortableRuleItem({
    ruleId,
    reorderable,
    children,
}: PropsWithChildren<{ ruleId: ErrorTrackingRule['id']; reorderable: boolean }>): JSX.Element {
    const { setNodeRef, attributes, transform, transition, listeners, active, isDragging } = useSortable({ id: ruleId })

    return (
        <div
            className={cn('flex gap-2', isDragging && 'z-[999999]')}
            ref={setNodeRef}
            style={{
                transform: CSS.Translate.toString(transform),
                transition,
            }}
            {...attributes}
        >
            {reorderable && (
                <SortableDragIcon
                    className={cn('rotate-90 w-5 h-5 mt-4', active ? 'cursor-grabbing' : 'cursor-grab')}
                    {...listeners}
                />
            )}
            <div className="flex-1">{children}</div>
        </div>
    )
}
