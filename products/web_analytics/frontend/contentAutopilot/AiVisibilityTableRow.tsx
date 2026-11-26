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
    expandedRowClassName,
}: {
    record: T
    index: number
    rowCount: number
    columns: AiVisibilityColumn<T>[]
    columnCount: number
    props: Pick<LemonTableProps<T>, 'rowStatus' | 'rowClassName' | 'onRow' | 'expandable'>
    expanded: boolean
    onToggleExpanded: () => void
    expandedRowClassName?: string
}): JSX.Element {
    const { expandable } = props
    const status = forRow(props.rowStatus, record, index)
    // Lemon's onRow type allows a string ref, which a quill row can't take, so it's dropped.
    const { className: rowPropsClassName, ref: _ref, ...rowProps } = props.onRow?.(record, index) ?? {}
    // As in the Lemon table, rowExpandable may return a number, and 0 or less means the row can't expand.
    const canExpand =
        expandable?.showRowExpansionToggle !== false &&
        (!expandable?.rowExpandable || Number(expandable.rowExpandable(record, index)) > 0)
    return (
        <Fragment>
            <TableRow
                {...rowProps}
                data-state={status ? 'selected' : undefined}
                className={cn(
                    rowProps.onClick && 'cursor-pointer',
                    forRow(props.rowClassName, record, index),
                    rowPropsClassName
                )}
            >
                {expandable ? (
                    <TableCell className="w-0">
                        {canExpand ? (
                            <AiVisibilityTableExpandButton expanded={expanded} onToggle={onToggleExpanded} />
                        ) : null}
                    </TableCell>
                ) : null}
                {columns.map((column, columnIndex) => {
                    const { className, style, content } = cellParts(column, record, index, rowCount)
                    return (
                        <TableCell
                            key={columnKey(column, columnIndex)}
                            align={column.align}
                            expand={column.fullWidth}
                            className={cn(column.width === 0 && 'w-0', className)}
                            style={style}
                        >
                            {content}
                        </TableCell>
                    )
                })}
            </TableRow>
            {expandable && expanded ? (
                <TableRow className={expandedRowClassName}>
                    <TableCell colSpan={columnCount}>{expandable.expandedRowRender(record, index)}</TableCell>
                </TableRow>
            ) : null}
        </Fragment>
    )
}
