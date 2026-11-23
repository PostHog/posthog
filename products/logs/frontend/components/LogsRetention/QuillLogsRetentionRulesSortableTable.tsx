import { DndContext, DragEndEvent, SensorDescriptor, SensorOptions, closestCenter } from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'

import { IconPlus } from '@posthog/icons'
import { Button, Skeleton, Table, TableBody, TableEmpty, TableHead, TableHeader, TableRow, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { LogsRetentionRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { ruleEnabledToggleDisabledReason } from '../ruleEnabledToggleDisabledReason'
import { QuillLogsRetentionRuleRow } from './QuillLogsRetentionRuleRow'
import { retentionDaysLabel } from './retentionDaysLabel'
import { RetentionRulesProduct } from './retentionRulesProduct'

export interface QuillLogsRetentionRulesSortableTableProps {
    product: RetentionRulesProduct
    rules: LogsRetentionRuleApi[]
    initialLoading: boolean
    reloading: boolean
    sensors: SensorDescriptor<SensorOptions>[]
    dragDisabledReason: string | null
    ruleEnabledTogglePendingId: string | null
    saveRulesOrderPending: boolean
    onDraggingChange: (isDragging: boolean) => void
    onDragEnd: (event: DragEndEvent) => void
    onSetRuleEnabled: (ruleId: string, enabled: boolean) => void
    onRefresh: () => void
}

export function QuillLogsRetentionRulesSortableTable({
    product,
    rules,
    initialLoading,
    reloading,
    sensors,
    dragDisabledReason,
    ruleEnabledTogglePendingId,
    saveRulesOrderPending,
    onDraggingChange,
    onDragEnd,
    onSetRuleEnabled,
    onRefresh,
}: QuillLogsRetentionRulesSortableTableProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap justify-end gap-2">
                <Button variant="primary" render={<LinkPrimitive to={product.urls.newRule()} />}>
                    <IconPlus />
                    New retention rule
                </Button>
            </div>
            {initialLoading ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            ) : (
                <div className={cn(reloading && 'pointer-events-none opacity-70')}>
                    <DndContext
                        sensors={sensors}
                        collisionDetection={closestCenter}
                        onDragStart={() => onDraggingChange(true)}
                        onDragEnd={onDragEnd}
                        onDragCancel={() => onDraggingChange(false)}
                        modifiers={[restrictToVerticalAxis]}
                    >
                        <Table fullWidth>
                            <TableHeader>
                                <TableRow>
                                    <TableHead className="w-10">
                                        <span className="sr-only">Reorder</span>
                                    </TableHead>
                                    <TableHead className="w-12">Order</TableHead>
                                    <TableHead expand>Name</TableHead>
                                    <TableHead className="whitespace-nowrap">Retention</TableHead>
                                    <TableHead className="w-32">Enabled</TableHead>
                                </TableRow>
                            </TableHeader>
                            {rules.length === 0 ? (
                                <TableEmpty>No retention rules yet</TableEmpty>
                            ) : (
                                <TableBody>
                                    <SortableContext
                                        items={rules.map((r) => r.id)}
                                        strategy={verticalListSortingStrategy}
                                    >
                                        {rules.map((row, index) => (
                                            <QuillLogsRetentionRuleRow
                                                key={row.id}
                                                row={row}
                                                detailUrl={product.urls.ruleDetail(row.id)}
                                                orderIndex={index}
                                                retentionLabel={retentionDaysLabel(row)}
                                                dragDisabledReason={dragDisabledReason}
                                                enabledDisabledReason={ruleEnabledToggleDisabledReason(
                                                    row.id,
                                                    ruleEnabledTogglePendingId,
                                                    saveRulesOrderPending
                                                )}
                                                onSetRuleEnabled={onSetRuleEnabled}
                                            />
                                        ))}
                                    </SortableContext>
                                </TableBody>
                            )}
                        </Table>
                    </DndContext>
                </div>
            )}
            {!initialLoading && (
                <div>
                    <Button variant="outline" onClick={() => onRefresh()}>
                        Refresh list
                    </Button>
                </div>
            )}
        </div>
    )
}
