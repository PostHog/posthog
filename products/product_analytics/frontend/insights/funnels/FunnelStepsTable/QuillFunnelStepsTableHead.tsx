import { ReactNode } from 'react'

import { TableHead } from '@posthog/quill'

import { Sorting, getNextSorting } from 'lib/lemon-ui/LemonTable/sorting'

import { QuillColumnSortButton } from 'products/product_analytics/frontend/insights/shared/InsightsTable/columns/QuillColumnSortButton'

interface QuillFunnelStepsTableHeadProps {
    columnKey: string
    title: string
    sorting: Sorting | null
    onSort: (sorting: Sorting | null) => void
    before?: ReactNode
    align?: 'right'
    sticky?: 'left'
    className?: string
}

export function QuillFunnelStepsTableHead({
    columnKey,
    title,
    sorting,
    onSort,
    before,
    align,
    sticky,
    className,
}: QuillFunnelStepsTableHeadProps): JSX.Element {
    const order = sorting?.columnKey === columnKey ? sorting.order : null

    return (
        <TableHead
            align={align}
            sticky={sticky}
            className={className}
            aria-sort={order === 1 ? 'ascending' : order === -1 ? 'descending' : undefined}
        >
            {before}
            <QuillColumnSortButton order={order} onClick={() => onSort(getNextSorting(sorting, columnKey, false))}>
                {title}
            </QuillColumnSortButton>
        </TableHead>
    )
}
