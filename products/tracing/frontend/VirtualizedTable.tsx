import { CSSProperties, ReactNode, useMemo, useState } from 'react'
import { List } from 'react-window'

import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'
import { cn } from 'lib/utils/css-classes'

// Config-driven virtualized table: owns react-window virtualization, client-side sort, and the
// header/row layout; callers pass column definitions + data. Extracted from TraceCompareTable so
// the compare view and the operations view share one implementation. The column-def contract
// mirrors logs' `VirtualizedTableColumn` (products/logs/frontend/components/VirtualizedLogsList);
// the two are intended to converge into a single shared lib/ primitive later.

const ROW_HEIGHT = 44
const HEADER_HEIGHT = 32
// Min width a flex (width-less) column reserves when computing the horizontal-scroll row width.
const FLEX_MIN_WIDTH = 200

export type VirtualizedSortOrder = 1 | -1

export interface VirtualizedTableColumn<T> {
    key: string
    title: ReactNode
    /** Fixed column width in px. Omit to flex-fill the remaining space. */
    width?: number
    align?: 'right'
    /** Header tooltip. */
    tooltip?: string
    render: (record: T) => ReactNode
    /** Provide to make the column sortable. */
    sorter?: (a: T, b: T) => number
}

function Cell({ width, align, children }: { width?: number; align?: 'right'; children: ReactNode }): JSX.Element {
    return (
        <div
            className={cn(
                'shrink-0 truncate px-2 text-xs',
                width === undefined && 'flex-1 min-w-0',
                align === 'right' && 'text-right'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={width !== undefined ? { width } : undefined}
        >
            {children}
        </div>
    )
}

function HeaderCell({
    column,
    sortKey,
    sortOrder,
    onSort,
}: {
    column: VirtualizedTableColumn<any>
    sortKey: string | null
    sortOrder: VirtualizedSortOrder
    onSort: (key: string) => void
}): JSX.Element {
    const label = column.tooltip ? <Tooltip title={column.tooltip}>{column.title}</Tooltip> : column.title
    if (!column.sorter) {
        return (
            <Cell width={column.width} align={column.align}>
                {label}
            </Cell>
        )
    }
    const active = sortKey === column.key
    return (
        <Cell width={column.width} align={column.align}>
            <button
                type="button"
                className={cn(
                    'flex items-center cursor-pointer hover:text-default',
                    column.align === 'right' && 'ml-auto',
                    active && 'text-default'
                )}
                onClick={() => onSort(column.key)}
                data-attr={`virtualized-table-sort-${column.key}`}
            >
                <span>{label}</span>
                <SortingIndicator order={active ? sortOrder : null} />
            </button>
        </Cell>
    )
}

// The generic T is erased to `any` at the react-window row boundary — type safety lives at the
// column-definition site (`columns: VirtualizedTableColumn<T>[]`), not inside the row renderer.
interface VirtualizedRowProps {
    columns: VirtualizedTableColumn<any>[]
    dataSource: any[]
    rowKey: (record: any) => string
    onRowClick?: (record: any) => void
}

function VirtualizedRow({
    ariaAttributes,
    index,
    style,
    columns,
    dataSource,
    rowKey,
    onRowClick,
}: {
    ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' }
    index: number
    style: CSSProperties
} & VirtualizedRowProps): JSX.Element {
    const record = dataSource[index]
    return (
        <div
            {...ariaAttributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            data-index={index}
            data-row-key={rowKey(record)}
        >
            <div
                className={cn(
                    'flex items-center border-b border-border hover:bg-surface-primary-hover',
                    onRowClick && 'cursor-pointer'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: ROW_HEIGHT }}
                onClick={onRowClick ? () => onRowClick(record) : undefined}
                onKeyDown={
                    onRowClick
                        ? (e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault()
                                  onRowClick(record)
                              }
                          }
                        : undefined
                }
                role={onRowClick ? 'button' : undefined}
                tabIndex={onRowClick ? 0 : undefined}
            >
                {columns.map((column) => (
                    <Cell key={column.key} width={column.width} align={column.align}>
                        {column.render(record)}
                    </Cell>
                ))}
            </div>
        </div>
    )
}

export interface VirtualizedTableProps<T> {
    columns: VirtualizedTableColumn<T>[]
    dataSource: T[]
    loading: boolean
    rowKey: (record: T) => string
    onRowClick?: (record: T) => void
    defaultSort?: { columnKey: string; order: VirtualizedSortOrder }
    emptyLabel?: string
    'data-attr'?: string
}

export function VirtualizedTable<T>({
    columns,
    dataSource,
    loading,
    rowKey,
    onRowClick,
    defaultSort,
    emptyLabel = 'No rows',
    'data-attr': dataAttr,
}: VirtualizedTableProps<T>): JSX.Element {
    const [sortKey, setSortKey] = useState<string | null>(defaultSort?.columnKey ?? null)
    const [sortOrder, setSortOrder] = useState<VirtualizedSortOrder>(defaultSort?.order ?? -1)

    const minRowWidth = useMemo(
        () => columns.reduce((sum, column) => sum + (column.width ?? FLEX_MIN_WIDTH), 0),
        [columns]
    )

    const rows = useMemo(() => {
        const sorter = columns.find((column) => column.key === sortKey)?.sorter
        if (!sorter) {
            return dataSource
        }
        return [...dataSource].sort((a, b) => sorter(a, b) * sortOrder)
    }, [dataSource, columns, sortKey, sortOrder])

    const onSort = (key: string): void => {
        if (key === sortKey) {
            setSortOrder((order) => (order === 1 ? -1 : 1))
        } else {
            setSortKey(key)
            setSortOrder(-1)
        }
    }

    const rowProps = useMemo(
        (): VirtualizedRowProps => ({ columns, dataSource: rows, rowKey, onRowClick }),
        [columns, rows, rowKey, onRowClick]
    )

    if (rows.length === 0) {
        return (
            <div className="flex items-center justify-center p-8 text-muted border rounded bg-bg-light">
                {loading ? <Spinner className="text-2xl" /> : emptyLabel}
            </div>
        )
    }

    return (
        <div className="flex flex-col flex-1 min-h-0 bg-bg-light border rounded overflow-hidden" data-attr={dataAttr}>
            <AutoSizer
                renderProp={({ width, height }: SizeProps) => {
                    if (!width || !height) {
                        return null
                    }
                    const rowWidth = Math.max(width, minRowWidth)
                    return (
                        // The viewport is fixed to the available box; inner content can be wider
                        // (minRowWidth) so columns scroll horizontally and rows align with the header.
                        // eslint-disable-next-line react/forbid-dom-props
                        <div className="overflow-x-auto" style={{ width, height }}>
                            {/* eslint-disable-next-line react/forbid-dom-props */}
                            <div style={{ width: rowWidth }}>
                                <div
                                    className="flex items-center border-b border-border bg-surface-secondary font-medium text-muted"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ height: HEADER_HEIGHT }}
                                >
                                    {columns.map((column) => (
                                        <HeaderCell
                                            key={column.key}
                                            column={column}
                                            sortKey={sortKey}
                                            sortOrder={sortOrder}
                                            onSort={onSort}
                                        />
                                    ))}
                                </div>
                                <List<VirtualizedRowProps>
                                    style={{ height: height - HEADER_HEIGHT, width: rowWidth }}
                                    overscanCount={10}
                                    rowCount={rows.length}
                                    rowHeight={ROW_HEIGHT}
                                    rowComponent={VirtualizedRow}
                                    rowProps={rowProps}
                                />
                            </div>
                        </div>
                    )
                }}
            />
        </div>
    )
}
