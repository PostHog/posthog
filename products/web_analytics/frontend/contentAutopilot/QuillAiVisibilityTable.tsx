import { useMemo, useState } from 'react'

import { Skeleton, Table, TableBody, TableCell, TableEmpty, TableRow, Text, cn } from '@posthog/quill'

import type { LemonTableProps } from 'lib/lemon-ui/LemonTable'
import type { Sorting } from 'lib/lemon-ui/LemonTable/sorting'

import { type AiVisibilityColumn, columnKey, isGrouped } from './aiVisibilityTableColumns'
import { pagerState } from './aiVisibilityTablePaging'
import { QuillAiVisibilityTableHeader } from './QuillAiVisibilityTableHeader'
import { QuillAiVisibilityTablePager } from './QuillAiVisibilityTablePager'
import { QuillAiVisibilityTableRow } from './QuillAiVisibilityTableRow'

const EmptyState = ({ emptyState }: { emptyState: React.ReactNode }): JSX.Element =>
    typeof emptyState === 'string' || emptyState === undefined ? (
        <Text size="xs" variant="muted" render={<span />}>
            {emptyState ?? 'No data'}
        </Text>
    ) : (
        <>{emptyState}</>
    )

/** The quill view of a LemonTable in AI visibility: the same columns, sorting, expansion and paging, drawn in quill. */
export function QuillAiVisibilityTable<T extends Record<string, any>>(props: LemonTableProps<T>): JSX.Element {
    const { columns, dataSource, rowKey, size, loading, loadingSkeletonRows = 1, emptyState, expandable } = props
    const { pagination, defaultSorting = null, footer, 'data-attr': dataAttr } = props
    const [sorting, setSorting] = useState<Sorting | null>(defaultSorting)
    const [expanded, setExpanded] = useState<Set<string | number>>(new Set())
    const [autoPage, setAutoPage] = useState(1)

    const groups = isGrouped(columns) ? columns : null
    const flat: AiVisibilityColumn<T>[] = groups
        ? groups.flatMap((group) => group.children)
        : (columns as AiVisibilityColumn<T>[])
    const visible = flat.filter((column) => !column.isHidden)
    const columnCount = visible.length + (expandable ? 1 : 0)

    const sorted = useMemo(() => {
        const sorter = visible.find((column, index) => columnKey(column, index) === sorting?.columnKey)?.sorter
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

    const toggleExpanded = (id: string | number): void =>
        setExpanded((current) => {
            const next = new Set(current)
            if (next.has(id)) {
                next.delete(id)
            } else {
                next.add(id)
            }
            return next
        })

    return (
        <div className="flex flex-col gap-2" data-attr={dataAttr}>
            <Table fullWidth size={size === 'small' ? 'sm' : 'default'}>
                <QuillAiVisibilityTableHeader<T>
                    groups={groups}
                    columns={visible}
                    expandable={!!expandable}
                    sorting={sorting}
                    onSortingChange={setSorting}
                />
                {loading && dataSource.length === 0 ? (
                    <TableBody>
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
                    <TableBody aria-busy={loading} className={cn(loading && 'opacity-50')}>
                        {rows.map((record, index) => {
                            const id = rowId(record, index)
                            return (
                                <QuillAiVisibilityTableRow<T>
                                    key={id}
                                    record={record}
                                    index={index}
                                    rowCount={rows.length}
                                    columns={visible}
                                    columnCount={columnCount}
                                    props={props}
                                    expanded={expanded.has(id)}
                                    onToggleExpanded={() => toggleExpanded(id)}
                                />
                            )
                        })}
                    </TableBody>
                )}
            </Table>
            {pager.show ? (
                <QuillAiVisibilityTablePager {...pager} onBackward={() => turnPage(-1)} onForward={() => turnPage(1)} />
            ) : null}
            {footer}
        </div>
    )
}
