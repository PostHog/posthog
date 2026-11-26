import { useMemo, useState } from 'react'

import { Skeleton, Table, TableBody, TableCell, TableEmpty, TableRow, Text, cn } from '@posthog/quill'

import type { LemonTableProps } from 'lib/lemon-ui/LemonTable'
import type { Sorting } from 'lib/lemon-ui/LemonTable/sorting'

import { type AiVisibilityColumn, columnKey, forRow, isGrouped } from './aiVisibilityTableColumns'
import { AiVisibilityTableHeader } from './AiVisibilityTableHeader'
import { AiVisibilityTablePager } from './AiVisibilityTablePager'
import { pagerState } from './aiVisibilityTablePaging'
import { AiVisibilityTableRow } from './AiVisibilityTableRow'

const EmptyState = ({ emptyState }: { emptyState: React.ReactNode }): JSX.Element =>
    typeof emptyState === 'string' || emptyState === undefined ? (
        <Text size="xs" variant="muted" render={<span />}>
            {emptyState ?? 'No data'}
        </Text>
    ) : (
        <>{emptyState}</>
    )

/**
 * Draws a Lemon table's props in quill: the same columns, sorting, expansion and paging.
 * The wrapper is the `ai-visibility-table` container, so a column's className can hide it with
 * `hidden @lg/ai-visibility-table:table-cell` when the table has no room for it.
 */
export function AiVisibilityTable<T extends Record<string, any>>(props: LemonTableProps<T>): JSX.Element {
    const { columns, dataSource, rowKey, size, loading, loadingSkeletonRows = 1, emptyState, expandable } = props
    const { pagination, defaultSorting = null, footer, className, 'data-attr': dataAttr } = props
    const [localSorting, setLocalSorting] = useState<Sorting | null>(defaultSorting)
    const [expanded, setExpanded] = useState<Set<string | number>>(new Set())
    const [autoPage, setAutoPage] = useState(1)

    const sorting = props.sorting !== undefined ? props.sorting : localSorting
    const setSorting = (next: Sorting | null): void => {
        props.onSort?.(next)
        if (props.sorting === undefined) {
            setLocalSorting(next)
        }
    }

    const groups = isGrouped(columns) ? columns : null
    const visible = useMemo(
        () =>
            (groups ? groups.flatMap((group) => group.children) : (columns as AiVisibilityColumn<T>[])).filter(
                (column) => !column.isHidden
            ),
        [columns, groups]
    )
    const columnCount = visible.length + (expandable ? 1 : 0)

    const sorted = useMemo(() => {
        const sorter = visible.find((column, index) => columnKey(column, index) === sorting?.columnKey)?.sorter
        // `sorter: true` means the caller sorts on the server, so the rows already come in order.
        return sorting && typeof sorter === 'function'
            ? [...dataSource].sort((a, b) => sorter(a, b) * sorting.order)
            : dataSource
    }, [dataSource, sorting, visible])

    const pager = pagerState(pagination, autoPage, sorted.length)
    const rows = pager.slice ? sorted.slice(pager.slice[0], pager.slice[1]) : sorted

    const turnPage = (step: 1 | -1): void => {
        if (pagination?.controlled) {
            ;(step === 1 ? pagination.onForward : pagination.onBackward)?.()
        } else {
            setAutoPage(pager.page + step)
        }
    }

    const rowId = (record: T, index: number): string | number =>
        typeof rowKey === 'function' ? rowKey(record, index) : rowKey ? record[rowKey] : index

    const isExpanded = (record: T, index: number, id: string | number): boolean => {
        const override = expandable?.isRowExpanded?.(record, index)
        return override === undefined || Number(override) < 0 ? expanded.has(id) : !!override
    }

    const toggleExpanded = (record: T, index: number, id: string | number): void => {
        const opening = !isExpanded(record, index, id)
        ;(opening ? expandable?.onRowExpand : expandable?.onRowCollapse)?.(record, index)
        setExpanded((current) => {
            const next = new Set(current)
            if (opening) {
                next.add(id)
            } else {
                next.delete(id)
            }
            return next
        })
    }

    return (
        <div
            className={cn('@container/ai-visibility-table flex min-w-0 flex-col gap-2', className)}
            data-attr={dataAttr}
        >
            <Table fullWidth size={size === 'small' ? 'sm' : 'default'}>
                {props.showHeader === false ? null : (
                    <AiVisibilityTableHeader<T>
                        groups={groups}
                        columns={visible}
                        expandable={!!expandable}
                        sorting={sorting}
                        noSortingCancellation={!!props.noSortingCancellation}
                        onSortingChange={setSorting}
                    />
                )}
                {loading && dataSource.length === 0 ? (
                    <TableBody aria-busy>
                        {Array.from({ length: Math.max(loadingSkeletonRows, 3) }, (_, row) => (
                            <TableRow key={row}>
                                <TableCell colSpan={columnCount}>
                                    <Skeleton className="h-5 w-full" />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                ) : rows.length === 0 ? (
                    <TableEmpty>
                        <EmptyState emptyState={emptyState} />
                    </TableEmpty>
                ) : (
                    <TableBody aria-busy={!!loading} className={cn(loading && 'opacity-50')}>
                        {rows.map((record, index) => {
                            const id = rowId(record, index)
                            return (
                                <AiVisibilityTableRow<T>
                                    key={id}
                                    record={record}
                                    index={index}
                                    rowCount={rows.length}
                                    columns={visible}
                                    columnCount={columnCount}
                                    props={props}
                                    expanded={isExpanded(record, index, id)}
                                    onToggleExpanded={() => toggleExpanded(record, index, id)}
                                    expandedRowClassName={
                                        forRow<T, string | null | undefined>(
                                            expandable?.expandedRowClassName,
                                            record,
                                            index
                                        ) ?? undefined
                                    }
                                />
                            )
                        })}
                    </TableBody>
                )}
            </Table>
            {pager.show ? (
                <AiVisibilityTablePager {...pager} onBackward={() => turnPage(-1)} onForward={() => turnPage(1)} />
            ) : null}
            {footer}
        </div>
    )
}
