import type { LemonTableColumn, LemonTableColumnGroup, LemonTableProps } from 'lib/lemon-ui/LemonTable'

export type AiVisibilityColumn<T extends Record<string, any>> = LemonTableColumn<T, keyof T | undefined>

export const isGrouped = <T extends Record<string, any>>(
    columns: LemonTableProps<T>['columns']
): columns is LemonTableColumnGroup<T>[] => columns.length > 0 && 'children' in columns[0]

export const columnKey = <T extends Record<string, any>>(column: AiVisibilityColumn<T>, index: number): string =>
    column.key ?? (typeof column.dataIndex === 'string' ? column.dataIndex : String(index))

export const columnValue = <T extends Record<string, any>>(column: AiVisibilityColumn<T>, record: T): any =>
    column.dataIndex !== undefined ? record[column.dataIndex as keyof T] : undefined

export const forRow = <T, V>(value: V | ((record: T, index: number) => V), record: T, index: number): V =>
    typeof value === 'function' ? (value as (record: T, index: number) => V)(record, index) : value

export const columnWidth = <T extends Record<string, any>>(
    column: AiVisibilityColumn<T>
): React.CSSProperties | undefined =>
    column.width === undefined || column.width === 0 ? undefined : { width: column.width }

export const cellParts = <T extends Record<string, any>>(
    column: AiVisibilityColumn<T>,
    record: T,
    index: number,
    rowCount: number
): { className: string | undefined; style: React.CSSProperties | undefined; content: React.ReactNode } => {
    const value = columnValue(column, record)
    const className = typeof column.className === 'function' ? column.className(value, record, index) : column.className
    const style = typeof column.style === 'function' ? column.style(value, record, index) : column.style
    return {
        className,
        style: { ...columnWidth(column), ...style },
        content: column.render ? column.render(value, record, index, rowCount) : value,
    }
}
