import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { Button, Switch, TableCell, TableRow, Text, cn } from '@posthog/quill'

import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { compactNumber, humanizeBytes } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { LogsSamplingRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { ruleTypeLabel } from './ruleTypeLabel'
import { type SamplingRuleDropTotals } from './samplingRuleDropImpact'

export interface QuillLogsSamplingRuleRowProps {
    row: LogsSamplingRuleApi
    orderIndex: number
    dragDisabledReason: string | null
    enabledDisabledReason: string | undefined
    ruleDropImpactCellState: 'loading' | 'ok' | 'error' | 'unknown'
    impact24h: SamplingRuleDropTotals
    onSetRuleEnabled: (ruleId: string, enabled: boolean) => void
}

export function QuillLogsSamplingRuleRow({
    row,
    orderIndex,
    dragDisabledReason,
    enabledDisabledReason,
    ruleDropImpactCellState,
    impact24h,
    onSetRuleEnabled,
}: QuillLogsSamplingRuleRowProps): JSX.Element {
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
                    render={<LinkPrimitive to={urls.logsSamplingDetail(row.id)} />}
                    data-attr="logs-drop-rule-link"
                >
                    {row.name}
                </Button>
            </TableCell>
            <TableCell>
                <Text size="xs" variant="muted" render={<span />}>
                    {ruleTypeLabel(row.rule_type)}
                </Text>
            </TableCell>
            <TableCell className="whitespace-nowrap">
                {ruleDropImpactCellState === 'loading' ? (
                    <Text size="xs" variant="muted" render={<span />}>
                        …
                    </Text>
                ) : ruleDropImpactCellState === 'ok' ? (
                    <Text size="xs" render={<span />} translate="no">
                        <span>~{compactNumber(impact24h.records)} dropped</span>
                        {impact24h.bytes > 0 && (
                            <Text size="xs" variant="muted" render={<span />}>
                                {` · ~${humanizeBytes(impact24h.bytes)}`}
                            </Text>
                        )}{' '}
                        <Text size="xs" variant="muted" render={<span />}>
                            (24h)
                        </Text>
                    </Text>
                ) : (
                    <Text
                        size="xs"
                        variant="muted"
                        render={<span />}
                        title={
                            ruleDropImpactCellState === 'error'
                                ? 'Could not load 24h drop totals'
                                : 'Drop impact not available'
                        }
                    >
                        –
                    </Text>
                )}
            </TableCell>
            <TableCell className="w-32">
                <Switch
                    checked={row.enabled ?? false}
                    onCheckedChange={(checked) => onSetRuleEnabled(row.id, checked)}
                    disabledReason={enabledDisabledReason}
                    aria-label={`Enable ${row.name}`}
                    data-attr="logs-drop-rule-enabled-switch"
                />
            </TableCell>
        </TableRow>
    )
}
