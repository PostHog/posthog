import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { Button, Switch, TableCell, TableRow, Text, cn } from '@posthog/quill'

import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { LogsRetentionRuleApi } from 'products/logs/frontend/generated/api.schemas'

export interface QuillLogsRetentionRuleRowProps {
    row: LogsRetentionRuleApi
    detailUrl: string
    orderIndex: number
    retentionLabel: string
    dragDisabledReason: string | null
    enabledDisabledReason: string | undefined
    onSetRuleEnabled: (ruleId: string, enabled: boolean) => void
}

export function QuillLogsRetentionRuleRow({
    row,
    detailUrl,
    orderIndex,
    retentionLabel,
    dragDisabledReason,
    enabledDisabledReason,
    onSetRuleEnabled,
}: QuillLogsRetentionRuleRowProps): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: row.id,
        disabled: Boolean(dragDisabledReason),
    })

    const style = {
        transform: CSS.Transform.toString(transform),
        transition: isDragging ? 'none' : transition,
        zIndex: isDragging ? 10 : ('auto' as const),
    }

    return (
        <TableRow
            ref={dragDisabledReason ? undefined : setNodeRef}
            style={style}
            className={cn('relative', isDragging && 'bg-background opacity-85 shadow-md')}
        >
            <TableCell className="w-10">
                <Button
                    size="icon-sm"
                    aria-label="Drag to reorder"
                    disabledReason={dragDisabledReason}
                    className={cn(!dragDisabledReason && 'cursor-grab active:cursor-grabbing')}
                    {...(dragDisabledReason ? {} : attributes)}
                    {...(dragDisabledReason ? {} : listeners)}
                >
                    <SortableDragIcon />
                </Button>
            </TableCell>
            <TableCell className="w-12" align="center">
                <Text size="xs" variant="muted" render={<span />}>
                    {orderIndex + 1}
                </Text>
            </TableCell>
            <TableCell expand>
                <Button
                    variant="link-foreground"
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={detailUrl} />}
                    data-attr="logs-retention-rule-link"
                >
                    {row.name}
                </Button>
            </TableCell>
            <TableCell className="whitespace-nowrap">
                <Text size="xs" variant="muted" render={<span />}>
                    {retentionLabel}
                </Text>
            </TableCell>
            <TableCell className="w-32">
                <Switch
                    checked={row.enabled ?? false}
                    onCheckedChange={(checked) => onSetRuleEnabled(row.id, checked)}
                    disabledReason={enabledDisabledReason}
                    aria-label={`Enable ${row.name}`}
                    data-attr="logs-retention-rule-enabled-switch"
                />
            </TableCell>
        </TableRow>
    )
}
