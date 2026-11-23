import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { PropsWithChildren, ReactNode } from 'react'

import { Button, cn } from '@posthog/quill'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

import { ErrorTrackingRule } from './types'

export function QuillSortableRuleItem({
    ruleId,
    reorderable,
    leading,
    children,
}: PropsWithChildren<{ ruleId: ErrorTrackingRule['id']; reorderable: boolean; leading?: ReactNode }>): JSX.Element {
    const { setNodeRef, attributes, transform, transition, listeners, isDragging } = useSortable({ id: ruleId })

    return (
        <div
            ref={setNodeRef}
            style={{
                transform: CSS.Translate.toString(transform),
                transition: isDragging ? 'none' : transition,
            }}
            className={cn('relative flex gap-2', isDragging && 'z-10 opacity-85')}
        >
            {reorderable && (
                <div className="flex shrink-0 items-start pt-2">
                    <Button
                        size="icon-sm"
                        aria-label="Drag to reorder"
                        className="cursor-grab active:cursor-grabbing"
                        {...attributes}
                        {...listeners}
                    >
                        <SortableDragIcon className="rotate-90" />
                    </Button>
                </div>
            )}
            {leading && <div className="flex shrink-0 items-start pt-2">{leading}</div>}
            <div className="min-w-0 flex-1">{children}</div>
        </div>
    )
}
