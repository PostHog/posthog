import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

import { ColumnResizeHandle, ColumnResizeHandleProps } from './ColumnResizeHandle'

export interface TableHeaderCellProps {
    width: number
    align?: 'right'
    /** Omit on the last column, where there is nothing to the right to give or take space. */
    resize?: Omit<ColumnResizeHandleProps, 'width'>
    children: ReactNode
}

/** Header cell of a tracing virtualized table, with the resize grab bar on its right edge. */
export function TableHeaderCell({ width, align, resize, children }: TableHeaderCellProps): JSX.Element {
    return (
        <div
            className="relative flex h-full shrink-0 items-center"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width }}
        >
            <div className={cn('w-full truncate px-2 text-xs', align === 'right' && 'text-right')}>{children}</div>
            {resize && <ColumnResizeHandle width={width} {...resize} />}
        </div>
    )
}
