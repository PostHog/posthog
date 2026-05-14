import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDrag } from '@posthog/icons'
import { LemonCheckbox, LemonInput, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { MonitorStatus, MonitorSummary } from '../uptimeSceneLogic'
import { statusPageLogic } from './statusPageLogic'

export function MonitorPicker(): JSX.Element {
    const { selectedMonitors, availableMonitors, monitorSummariesLoading } = useValues(statusPageLogic)
    const { toggleMonitor, reorderMonitors } = useActions(statusPageLogic)
    const [query, setQuery] = useState('')

    const sensors = useSensors(
        useSensor(PointerSensor, {
            // Without an activation distance, clicking the checkbox starts a drag instead of toggling.
            activationConstraint: { distance: 4 },
        })
    )

    const filteredSelected = filterByQuery(selectedMonitors, query)
    const filteredAvailable = filterByQuery(availableMonitors, query)

    const onDragEnd = ({ active, over }: DragEndEvent): void => {
        if (!over || active.id === over.id) {
            return
        }
        const currentIds = selectedMonitors.map((m) => m.id)
        const from = currentIds.indexOf(active.id as string)
        const to = currentIds.indexOf(over.id as string)
        if (from === -1 || to === -1) {
            return
        }
        reorderMonitors(arrayMove(currentIds, from, to))
    }

    return (
        <div className="flex flex-col gap-3 h-full">
            <LemonInput
                type="search"
                placeholder="Search monitors"
                value={query}
                onChange={setQuery}
                size="small"
                fullWidth
            />

            <div className="flex-1 overflow-y-auto flex flex-col gap-1">
                {selectedMonitors.length > 0 && <SectionLabel>On this page · {selectedMonitors.length}</SectionLabel>}
                <DndContext
                    sensors={sensors}
                    modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                    onDragEnd={onDragEnd}
                >
                    <SortableContext items={selectedMonitors.map((m) => m.id)} strategy={verticalListSortingStrategy}>
                        {filteredSelected.map((monitor) => (
                            <SortableRow
                                key={monitor.id}
                                monitor={monitor}
                                isSelected
                                onToggle={() => toggleMonitor(monitor.id)}
                            />
                        ))}
                    </SortableContext>
                </DndContext>

                {filteredAvailable.length > 0 && (
                    <>
                        <SectionLabel className={selectedMonitors.length > 0 ? 'mt-2' : undefined}>
                            Available · {filteredAvailable.length}
                        </SectionLabel>
                        {filteredAvailable.map((monitor) => (
                            <MonitorRow
                                key={monitor.id}
                                monitor={monitor}
                                isSelected={false}
                                onToggle={() => toggleMonitor(monitor.id)}
                            />
                        ))}
                    </>
                )}

                {!monitorSummariesLoading && selectedMonitors.length === 0 && availableMonitors.length === 0 && (
                    <EmptyMonitorsState />
                )}

                {!monitorSummariesLoading && selectedMonitors.length + filteredAvailable.length === 0 && query && (
                    <div className="text-center text-xs text-secondary py-4">No monitors match "{query}"</div>
                )}
            </div>
        </div>
    )
}

function SortableRow({
    monitor,
    isSelected,
    onToggle,
}: {
    monitor: MonitorSummary
    isSelected: boolean
    onToggle: () => void
}): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: monitor.id,
    })
    const style: React.CSSProperties = {
        transform: CSS.Transform.toString(transform),
        transition,
    }
    return (
        <div ref={setNodeRef} style={style} className={cn(isDragging && 'z-10')} {...attributes}>
            <MonitorRow monitor={monitor} isSelected={isSelected} onToggle={onToggle} dragHandleProps={listeners} />
        </div>
    )
}

function MonitorRow({
    monitor,
    isSelected,
    onToggle,
    dragHandleProps,
}: {
    monitor: MonitorSummary
    isSelected: boolean
    onToggle: () => void
    dragHandleProps?: ReturnType<typeof useSortable>['listeners']
}): JSX.Element {
    return (
        <div
            className={cn(
                'group flex items-center gap-2 px-2 py-1.5 rounded transition-colors',
                isSelected ? 'bg-surface-secondary' : 'hover:bg-surface-secondary'
            )}
        >
            {isSelected && dragHandleProps ? (
                <button
                    type="button"
                    className="shrink-0 cursor-grab active:cursor-grabbing text-secondary opacity-60 hover:opacity-100"
                    aria-label="Drag to reorder"
                    {...dragHandleProps}
                >
                    <IconDrag />
                </button>
            ) : (
                <span className="shrink-0 w-4" aria-hidden />
            )}
            <LemonCheckbox checked={isSelected} onChange={onToggle} />
            <div className="flex-1 min-w-0 flex items-center gap-2">
                <span
                    className={cn('inline-block w-2 h-2 rounded-full shrink-0', dotClassFor(monitor.status))}
                    aria-hidden
                />
                <div className="flex flex-col min-w-0">
                    <span className="text-sm font-medium truncate">{monitor.name}</span>
                    <Link
                        to={monitor.url}
                        target="_blank"
                        className="text-[11px] text-secondary truncate"
                        title={monitor.url}
                    >
                        {monitor.url}
                    </Link>
                </div>
            </div>
        </div>
    )
}

function SectionLabel({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element {
    return (
        <div className={cn('px-2 py-1 text-[11px] uppercase tracking-wide text-secondary font-medium', className)}>
            {children}
        </div>
    )
}

function EmptyMonitorsState(): JSX.Element {
    return (
        <div className="text-center text-xs text-secondary py-6">
            No monitors yet. Create one from the Monitors tab to add it here.
        </div>
    )
}

function filterByQuery(monitors: MonitorSummary[], query: string): MonitorSummary[] {
    const q = query.trim().toLowerCase()
    if (!q) {
        return monitors
    }
    return monitors.filter((m) => m.name.toLowerCase().includes(q) || m.url.toLowerCase().includes(q))
}

function dotClassFor(status: MonitorStatus): string {
    if (status === 'up') {
        return 'bg-success'
    }
    if (status === 'down') {
        return 'bg-danger'
    }
    return 'bg-border-bold'
}
