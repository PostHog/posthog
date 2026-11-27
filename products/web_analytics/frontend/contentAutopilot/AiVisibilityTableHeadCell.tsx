import { IconInfo, IconSort } from '@posthog/icons'
import { Button, TableHead, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import { type AiVisibilityColumn, columnWidth } from './aiVisibilityTableColumns'

const HeaderLabel = ({ title, tooltip }: { title: React.ReactNode; tooltip?: string }): JSX.Element =>
    tooltip ? (
        <span className="inline-flex items-center gap-1">
            {title}
            <Tooltip>
                <TooltipTrigger delay={0} render={<span aria-label={tooltip} />}>
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
            </Tooltip>
        </span>
    ) : (
        <>{title}</>
    )

export function AiVisibilityTableHeadCell<T extends Record<string, any>>({
    column,
    order,
    onSort,
}: {
    column: AiVisibilityColumn<T>
    order: 1 | -1 | null
    onSort: () => void
}): JSX.Element {
    const label = <HeaderLabel title={column.title} tooltip={column.tooltip} />
    return (
        <TableHead
            align={column.align}
            expand={column.fullWidth}
            aria-sort={order === 1 ? 'ascending' : order === -1 ? 'descending' : undefined}
            style={columnWidth(column)}
            className={cn(column.width === 0 && 'w-0', typeof column.className === 'string' && column.className)}
        >
            {column.sorter ? (
                <Button size="sm" onClick={onSort}>
                    {label}
                    {order === 1 ? <IconArrowUp /> : order === -1 ? <IconArrowDown /> : <IconSort />}
                </Button>
            ) : (
                label
            )}
        </TableHead>
    )
}
