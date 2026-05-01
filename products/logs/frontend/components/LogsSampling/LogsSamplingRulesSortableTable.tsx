import {
    DndContext,
    DragEndEvent,
    KeyboardSensor,
    PointerSensor,
    closestCenter,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import {
    SortableContext,
    arrayMove,
    sortableKeyboardCoordinates,
    useSortable,
    verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { LogsSamplingRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { logsSamplingSectionLogic } from './logsSamplingSectionLogic'
import { ruleTypeLabel } from './ruleTypeLabel'

interface SortableRowProps {
    row: LogsSamplingRuleApi
    orderIndex: number
    disabledReason: string | null
    ruleEnabledTogglePendingId: string | null
    saveRulesOrderPending: boolean
    onSetRuleEnabled: (ruleId: string, enabled: boolean) => void
}

function SortableRow({
    row,
    orderIndex,
    disabledReason,
    ruleEnabledTogglePendingId,
    saveRulesOrderPending,
    onSetRuleEnabled,
}: SortableRowProps): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: row.id,
        disabled: Boolean(disabledReason),
    })

    const style = {
        transform: CSS.Transform.toString(transform),
        transition: isDragging ? 'none' : transition,
        opacity: isDragging ? 0.85 : 1,
        zIndex: isDragging ? 10 : ('auto' as const),
    }

    return (
        <tr
            ref={disabledReason ? undefined : setNodeRef}
            style={style}
            className={clsx('border-b border-border bg-bg-light hover:bg-bg-3000', {
                'shadow-md bg-bg-3000': isDragging,
            })}
        >
            <td className="py-2 px-2 w-10 align-middle">
                <div
                    className={clsx('flex items-center justify-center', {
                        'cursor-grab active:cursor-grabbing': !disabledReason,
                        'opacity-40': disabledReason,
                    })}
                    {...(disabledReason ? {} : attributes)}
                    {...(disabledReason ? {} : listeners)}
                >
                    <SortableDragIcon className="text-muted-alt h-3 w-3" />
                </div>
            </td>
            <td className="py-2 px-2 w-12 text-center text-muted text-sm font-medium align-middle">{orderIndex + 1}</td>
            <td className="py-2 px-2 min-w-0 align-middle">
                <LemonButton
                    size="small"
                    type="tertiary"
                    to={urls.logsSamplingDetail(row.id)}
                    data-attr="logs-drop-rule-link"
                >
                    <strong>{row.name}</strong>
                </LemonButton>
            </td>
            <td className="py-2 px-2 text-secondary text-sm align-middle">{ruleTypeLabel(row.rule_type)}</td>
            <td className="py-2 px-2 w-32 align-middle">
                <LemonSwitch
                    checked={row.enabled ?? false}
                    onChange={(checked) => onSetRuleEnabled(row.id, checked)}
                    disabledReason={
                        ruleEnabledTogglePendingId === row.id
                            ? 'Saving…'
                            : saveRulesOrderPending
                              ? 'Updating order…'
                              : undefined
                    }
                    data-attr="logs-drop-rule-enabled-switch"
                />
            </td>
        </tr>
    )
}

export function LogsSamplingRulesSortableTable(): JSX.Element {
    const { rules, rulesLoading, saveRulesOrderPending, ruleEnabledTogglePendingId } =
        useValues(logsSamplingSectionLogic)
    const { loadRules, saveRulesOrder, setRuleEnabled } = useActions(logsSamplingSectionLogic)

    const [localRules, setLocalRules] = useState<LogsSamplingRuleApi[]>(rules)
    const [isDragging, setIsDragging] = useState(false)

    useEffect(() => {
        if (!isDragging && !saveRulesOrderPending) {
            setLocalRules(rules)
        }
    }, [rules, isDragging, saveRulesOrderPending])

    const sensors = useSensors(
        useSensor(PointerSensor, {
            activationConstraint: { distance: 8 },
        }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )

    const handleDragEnd = (event: DragEndEvent): void => {
        setIsDragging(false)
        const { active, over } = event
        if (!over || active.id === over.id) {
            return
        }
        const oldIndex = localRules.findIndex((r) => r.id === active.id)
        const newIndex = localRules.findIndex((r) => r.id === over.id)
        if (oldIndex === -1 || newIndex === -1) {
            return
        }
        const next = arrayMove(localRules, oldIndex, newIndex)
        setLocalRules(next)
        saveRulesOrder(next.map((r) => r.id))
    }

    const dragDisabledReason =
        saveRulesOrderPending || rulesLoading
            ? 'Please wait…'
            : localRules.length < 2
              ? 'Add another rule to reorder'
              : null

    if (rulesLoading && rules.length === 0) {
        return (
            <div>
                <div className="flex justify-end mb-2">
                    <LemonButton type="primary" icon={<IconPlus />} to={urls.logsSamplingNew()}>
                        New drop rule
                    </LemonButton>
                </div>
                <div className="border border-border rounded-md bg-bg-light py-10 text-center text-muted">Loading…</div>
            </div>
        )
    }

    return (
        <div>
            <div className="flex justify-end mb-2">
                <LemonButton type="primary" icon={<IconPlus />} to={urls.logsSamplingNew()}>
                    New drop rule
                </LemonButton>
            </div>
            <div
                className={clsx('border border-border rounded-md overflow-hidden bg-bg-light', {
                    'opacity-70 pointer-events-none': rulesLoading && rules.length > 0,
                })}
            >
                <DndContext
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    onDragStart={() => setIsDragging(true)}
                    onDragEnd={handleDragEnd}
                    onDragCancel={() => setIsDragging(false)}
                    modifiers={[restrictToVerticalAxis]}
                >
                    <table className="w-full table-fixed">
                        <thead className="bg-bg-3000">
                            <tr>
                                <th className="py-2 px-2 w-10" />
                                <th className="py-2 px-2 w-12 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                    Order
                                </th>
                                <th className="py-2 px-2 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider min-w-0">
                                    Name
                                </th>
                                <th className="py-2 px-2 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider min-w-0">
                                    Type
                                </th>
                                <th className="py-2 px-2 w-32 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                    Enabled
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {localRules.length === 0 ? (
                                <tr>
                                    <td colSpan={5} className="text-center py-8 text-muted">
                                        No drop rules yet
                                    </td>
                                </tr>
                            ) : (
                                <SortableContext
                                    items={localRules.map((r) => r.id)}
                                    strategy={verticalListSortingStrategy}
                                >
                                    {localRules.map((row, index) => (
                                        <SortableRow
                                            key={row.id}
                                            row={row}
                                            orderIndex={index}
                                            disabledReason={dragDisabledReason}
                                            ruleEnabledTogglePendingId={ruleEnabledTogglePendingId}
                                            saveRulesOrderPending={saveRulesOrderPending}
                                            onSetRuleEnabled={setRuleEnabled}
                                        />
                                    ))}
                                </SortableContext>
                            )}
                        </tbody>
                    </table>
                </DndContext>
            </div>
            <div className="mt-2">
                <LemonButton size="small" type="secondary" onClick={() => loadRules()}>
                    Refresh list
                </LemonButton>
            </div>
        </div>
    )
}
