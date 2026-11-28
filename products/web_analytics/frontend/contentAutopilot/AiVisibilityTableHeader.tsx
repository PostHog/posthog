import { TableHead, TableHeader, TableRow } from '@posthog/quill'

import type { LemonTableColumnGroup } from 'lib/lemon-ui/LemonTable'
import { type Sorting, getNextSorting } from 'lib/lemon-ui/LemonTable/sorting'

import { type AiVisibilityColumn, columnKey } from './aiVisibilityTableColumns'
import { AiVisibilityTableHeadCell } from './AiVisibilityTableHeadCell'

export function AiVisibilityTableHeader<T extends Record<string, any>>({
    groups,
    columns,
    expandable,
    sorting,
    noSortingCancellation,
    onSortingChange,
}: {
    groups: LemonTableColumnGroup<T>[] | null
    columns: AiVisibilityColumn<T>[]
    expandable: boolean
    sorting: Sorting | null
    noSortingCancellation: boolean
    onSortingChange: (sorting: Sorting | null) => void
}): JSX.Element {
    return (
        <TableHeader>
            {groups ? (
                <TableRow>
                    {expandable ? <TableHead className="w-0" aria-label="Expand" /> : null}
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
                {columns.map((column, index) => {
                    const key = columnKey(column, index)
                    return (
                        <AiVisibilityTableHeadCell<T>
                            key={key}
                            column={column}
                            order={sorting?.columnKey === key ? sorting.order : null}
                            onSort={() =>
                                onSortingChange(
                                    getNextSorting(sorting, key, noSortingCancellation, column.defaultSortOrder)
                                )
                            }
                        />
                    )
                })}
            </TableRow>
        </TableHeader>
    )
}
