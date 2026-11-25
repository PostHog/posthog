import { Fragment, useMemo, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconInfo, IconSort } from '@posthog/icons'
import {
    Button,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import type { LemonTableColumn, LemonTableColumnGroup, LemonTableProps } from 'lib/lemon-ui/LemonTable'
import { type Sorting, getNextSorting } from 'lib/lemon-ui/LemonTable/sorting'

type Column<T extends Record<string, any>> = LemonTableColumn<T, keyof T | undefined>

const isGrouped = <T extends Record<string, any>>(
    columns: LemonTableProps<T>['columns']
): columns is LemonTableColumnGroup<T>[] => columns.length > 0 && 'children' in columns[0]

const keyOf = <T extends Record<string, any>>(column: Column<T>, index: number): string =>
    column.key ?? (typeof column.dataIndex === 'string' ? column.dataIndex : String(index))

const valueOf = <T extends Record<string, any>>(column: Column<T>, record: T): any =>
    column.dataIndex !== undefined ? record[column.dataIndex as keyof T] : undefined

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

/** The quill view of a LemonTable in AI visibility: the same columns, sorting, expansion and paging, drawn in quill. */
export function QuillAiVisibilityTable<T extends Record<string, any>>({
    columns,
    dataSource,
    rowKey,
    size,
    loading,
    loadingSkeletonRows = 1,
    emptyState,
    rowStatus,
    rowClassName,
    onRow,
    expandable,
    pagination,
    defaultSorting = null,
    footer,
    'data-attr': dataAttr,
}: LemonTableProps<T>): JSX.Element {
    const [sorting, setSorting] = useState<Sorting | null>(defaultSorting)
    const [expanded, setExpanded] = useState<Set<string | number>>(new Set())
    const [autoPage, setAutoPage] = useState(1)

    const groups = isGrouped(columns) ? columns : null
    const flat: Column<T>[] = groups ? groups.flatMap((group) => group.children) : (columns as Column<T>[])
    const visible = flat.filter((column) => !column.isHidden)
    const columnCount = visible.length + (expandable ? 1 : 0)

    const sorted = useMemo(() => {
        const sortColumn = sorting ? visible.find((column, index) => keyOf(column, index) === sorting.columnKey) : null
        if (!sorting || !sortColumn || typeof sortColumn.sorter !== 'function') {
            return dataSource
        }
        const sorter = sortColumn.sorter
        return [...dataSource].sort((a, b) => sorter(a, b) * sorting.order)
    }, [dataSource, sorting, visible])

    // Without a controlled pager, a page size splits the rows on the client, as the Lemon table does.
    const autoPageSize = pagination && !pagination.controlled ? pagination.pageSize : undefined
    const rows = autoPageSize ? sorted.slice((autoPage - 1) * autoPageSize, autoPage * autoPageSize) : sorted

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

    const page = pagination?.controlled ? (pagination.currentPage ?? 1) : autoPage
    const pageSize = pagination?.pageSize ?? 0
    const entryCount = pagination?.controlled ? (pagination.entryCount ?? 0) : sorted.length
    const canGoBack = pagination?.controlled ? !!pagination.onBackward && page > 1 : page > 1
    const canGoForward = pagination?.controlled ? !!pagination.onForward : page * pageSize < entryCount

    return (
        <div className="flex flex-col gap-2" data-attr={dataAttr}>
            <Table fullWidth size={size === 'small' ? 'sm' : 'default'}>
                <TableHeader>
                    {groups ? (
                        <TableRow>
                            {expandable ? <TableHead aria-label="Expand" /> : null}
                            {groups.map((group, index) => {
                                const span = group.children.filter((column) => !column.isHidden).length
                                return span > 0 ? (
                                    <TableHead key={index} colSpan={span}>
                                        {group.title}
                                    </TableHead>
                                ) : null
                            })}
                        </TableRow>
                    ) : null}
                    <TableRow>
                        {expandable ? <TableHead className="w-0" aria-label="Expand" /> : null}
                        {visible.map((column, index) => {
                            const key = keyOf(column, index)
                            const order = sorting?.columnKey === key ? sorting.order : null
                            return (
                                <TableHead key={key} align={column.align} className={cn(column.width === 0 && 'w-0')}>
                                    {column.sorter ? (
                                        <Button
                                            size="sm"
                                            className="-mx-2 uppercase"
                                            onClick={() =>
                                                setSorting(getNextSorting(sorting, key, false, column.defaultSortOrder))
                                            }
                                        >
                                            <HeaderLabel title={column.title} tooltip={column.tooltip} />
                                            {order === 1 ? (
                                                <IconArrowUp />
                                            ) : order === -1 ? (
                                                <IconArrowDown />
                                            ) : (
                                                <IconSort />
                                            )}
                                        </Button>
                                    ) : (
                                        <HeaderLabel title={column.title} tooltip={column.tooltip} />
                                    )}
                                </TableHead>
                            )
                        })}
                    </TableRow>
                </TableHeader>
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
                        {typeof emptyState === 'string' || emptyState === undefined ? (
                            <Text size="xs" variant="muted" render={<span />}>
                                {emptyState ?? 'No data'}
                            </Text>
                        ) : (
                            emptyState
                        )}
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {rows.map((record, index) => {
                            const id = rowId(record, index)
                            const status = typeof rowStatus === 'function' ? rowStatus(record, index) : rowStatus
                            const extraClass =
                                typeof rowClassName === 'function' ? rowClassName(record, index) : rowClassName
                            const rowProps = onRow?.(record, index) ?? {}
                            const expandableRow = expandable
                                ? (expandable.rowExpandable?.(record, index) ?? true) !== false
                                : false
                            const isExpanded = expanded.has(id)
                            return (
                                <Fragment key={id}>
                                    <TableRow
                                        onClick={rowProps.onClick}
                                        className={cn(
                                            status && 'bg-fill-selected',
                                            rowProps.onClick && 'cursor-pointer hover:bg-fill-hover',
                                            extraClass
                                        )}
                                    >
                                        {expandable ? (
                                            <TableCell>
                                                {expandableRow ? (
                                                    <Button
                                                        size="icon-sm"
                                                        aria-label={isExpanded ? 'Collapse row' : 'Expand row'}
                                                        aria-expanded={isExpanded}
                                                        onClick={(event) => {
                                                            event.stopPropagation()
                                                            toggleExpanded(id)
                                                        }}
                                                    >
                                                        {isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                                                    </Button>
                                                ) : null}
                                            </TableCell>
                                        ) : null}
                                        {visible.map((column, columnIndex) => {
                                            const value = valueOf(column, record)
                                            const cellClass =
                                                typeof column.className === 'function'
                                                    ? column.className(value, record, index)
                                                    : column.className
                                            return (
                                                <TableCell
                                                    key={keyOf(column, columnIndex)}
                                                    align={column.align}
                                                    className={cellClass}
                                                >
                                                    {column.render
                                                        ? column.render(value, record, index, rows.length)
                                                        : value}
                                                </TableCell>
                                            )
                                        })}
                                    </TableRow>
                                    {expandable && isExpanded ? (
                                        <TableRow>
                                            <TableCell colSpan={columnCount}>
                                                {expandable.expandedRowRender(record, index)}
                                            </TableCell>
                                        </TableRow>
                                    ) : null}
                                </Fragment>
                            )
                        })}
                    </TableBody>
                )}
            </Table>
            {pagination && entryCount > pageSize ? (
                <div className="flex items-center justify-end gap-2">
                    <Text size="xs" variant="muted" render={<span />}>
                        {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, entryCount)} of {entryCount}
                    </Text>
                    <Button
                        size="icon"
                        aria-label="Previous page"
                        tooltip="Previous page"
                        onClick={() =>
                            pagination.controlled ? pagination.onBackward?.() : setAutoPage((current) => current - 1)
                        }
                        disabledReason={canGoBack ? undefined : 'This is the first page'}
                    >
                        <IconChevronRight className="rotate-180" />
                    </Button>
                    <Button
                        size="icon"
                        aria-label="Next page"
                        tooltip="Next page"
                        onClick={() =>
                            pagination.controlled ? pagination.onForward?.() : setAutoPage((current) => current + 1)
                        }
                        disabledReason={canGoForward ? undefined : 'This is the last page'}
                    >
                        <IconChevronRight />
                    </Button>
                </div>
            ) : null}
            {footer}
        </div>
    )
}
