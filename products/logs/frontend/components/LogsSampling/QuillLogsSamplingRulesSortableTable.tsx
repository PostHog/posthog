import { DndContext, DragEndEvent, SensorDescriptor, SensorOptions, closestCenter } from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'

import { IconInfo, IconPlus } from '@posthog/icons'
import {
    Button,
    Skeleton,
    Table,
    TableBody,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { LogsSamplingRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { ruleEnabledToggleDisabledReason } from '../ruleEnabledToggleDisabledReason'
import { QuillLogsSamplingRuleRow } from './QuillLogsSamplingRuleRow'
import { type SamplingRuleDropTotals } from './samplingRuleDropImpact'

const EMPTY_IMPACT: SamplingRuleDropTotals = { records: 0, bytes: 0 }

export interface QuillLogsSamplingRulesSortableTableProps {
    rules: LogsSamplingRuleApi[]
    ruleDropImpact: Record<string, SamplingRuleDropTotals>
    ruleDropImpactCellState: 'loading' | 'ok' | 'error' | 'unknown'
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

export function QuillLogsSamplingRulesSortableTable({
    rules,
    ruleDropImpact,
    ruleDropImpactCellState,
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
}: QuillLogsSamplingRulesSortableTableProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap justify-end gap-2">
                <Button variant="primary" render={<LinkPrimitive to={urls.logsSamplingNew()} />}>
                    <IconPlus />
                    New drop rule
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
                                    <TableHead>Type</TableHead>
                                    <TableHead className="whitespace-nowrap">
                                        <span className="inline-flex items-center gap-1">
                                            Impact (24h)
                                            <Tooltip>
                                                <TooltipTrigger
                                                    delay={0}
                                                    render={<Button size="icon-xs" aria-label="About impact (24h)" />}
                                                >
                                                    <IconInfo />
                                                </TooltipTrigger>
                                                <TooltipContent className="max-w-80">
                                                    Log lines and bytes dropped by this rule in ingestion metrics. Bytes
                                                    appear once any drops have been attributed by the current producer
                                                    (older drops show records only). Rules scoped to a service only
                                                    affect that service; others count across the project.
                                                </TooltipContent>
                                            </Tooltip>
                                        </span>
                                    </TableHead>
                                    <TableHead className="w-32">Enabled</TableHead>
                                </TableRow>
                            </TableHeader>
                            {rules.length === 0 ? (
                                <TableEmpty>No drop rules yet</TableEmpty>
                            ) : (
                                <TableBody>
                                    <SortableContext
                                        items={rules.map((r) => r.id)}
                                        strategy={verticalListSortingStrategy}
                                    >
                                        {rules.map((row, index) => (
                                            <QuillLogsSamplingRuleRow
                                                key={row.id}
                                                row={row}
                                                orderIndex={index}
                                                dragDisabledReason={dragDisabledReason}
                                                enabledDisabledReason={ruleEnabledToggleDisabledReason(
                                                    row.id,
                                                    ruleEnabledTogglePendingId,
                                                    saveRulesOrderPending
                                                )}
                                                ruleDropImpactCellState={ruleDropImpactCellState}
                                                impact24h={ruleDropImpact[row.id] ?? EMPTY_IMPACT}
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
