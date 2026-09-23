import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

export interface TableCellProps {
    width: number
    align?: 'right'
    children: ReactNode
}

/** Body cell of a tracing virtualized table. Width comes from `useResizableColumns`. */
export function TableCell({ width, align, children }: TableCellProps): JSX.Element {
    return (
        <div
            className={cn('shrink-0 truncate px-2 text-xs', align === 'right' && 'text-right')}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width }}
        >
            {children}
        </div>
    )
}
