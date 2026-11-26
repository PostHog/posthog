import { Fragment } from 'react'

import { TableCell, TableRow, cn } from '@posthog/quill'

import type { LemonTableProps } from 'lib/lemon-ui/LemonTable'

import { type AiVisibilityColumn, cellParts, columnKey, forRow } from './aiVisibilityTableColumns'
import { AiVisibilityTableExpandButton } from './AiVisibilityTableExpandButton'

export function AiVisibilityTableRow<T extends Record<string, any>>({
    record,
    index,
    rowCount,
    columns,
    columnCount,
    props,
    expanded,
    onToggleExpanded,
}: {
    record: T
    index: number
    rowCount: number
    columns: AiVisibilityColumn<T>[]
    columnCount: number
    props: Pick<LemonTableProps<T>, 'rowStatus' | 'rowClassName' | 'onRow' | 'expandable'>
    expanded: boolean
    onToggleExpanded: () => void
}): JSX.Element {
    const { expandable } = props
    const status = forRow(props.rowStatus, record, index)
    const onClick = props.onRow?.(record, index)?.onClick
    // As in the Lemon table, rowExpandable may return a number, and 0 means the row can't expand.
    const canExpand = !expandable?.rowExpandable || !!expandable.rowExpandable(record, index)
    return (
        <Fragment>
            <TableRow
                onClick={onClick}
                className={cn(
                    status && 'bg-fill-selected',
                    onClick && 'cursor-pointer hover:bg-fill-hover',
                    forRow(props.rowClassName, record, index)
                )}
            >
                {expandable ? (
                    <TableCell>
                        {canExpand ? (
                            <AiVisibilityTableExpandButton expanded={expanded} onToggle={onToggleExpanded} />
                        ) : null}
                    </TableCell>
                ) : null}
                {columns.map((column, columnIndex) => {
                    const { className, content } = cellParts(column, record, index, rowCount)
                    return (
                        <TableCell key={columnKey(column, columnIndex)} align={column.align} className={className}>
                            {content}
                        </TableCell>
                    )
                })}
            </TableRow>
            {expandable && expanded ? (
                <TableRow>
                    <TableCell colSpan={columnCount}>{expandable.expandedRowRender(record, index)}</TableCell>
                </TableRow>
            ) : null}
        </Fragment>
    )
}
