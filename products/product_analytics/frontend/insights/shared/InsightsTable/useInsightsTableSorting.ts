import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { Sorting, getNextSorting } from 'lib/lemon-ui/LemonTable/sorting'

// pinned: the same search param LemonTable uses, so a shared link keeps its sort in either table
const SORTING_PARAM = 'order'

/** The table's sort, kept in the URL when `useURL` is set, the same way LemonTable keeps it. */
export function useInsightsTableSorting(useURL: boolean): [Sorting | null, (columnKey: string) => void] {
    const { location, searchParams, hashParams } = useValues(router)
    const { push } = useActions(router)
    const [internalSorting, setInternalSorting] = useState<Sorting | null>(null)

    const param: string | undefined = searchParams[SORTING_PARAM]
    // With the URL as the only source, Back and Forward move the sort along with the address.
    const sorting: Sorting | null = useURL
        ? param
            ? { columnKey: param.replace(/^-/, ''), order: param.startsWith('-') ? -1 : 1 }
            : null
        : internalSorting

    const toggleSorting = (columnKey: string): void => {
        const next = getNextSorting(sorting, columnKey, false)
        if (!useURL) {
            setInternalSorting(next)
        } else {
            push(
                location.pathname,
                {
                    ...searchParams,
                    [SORTING_PARAM]: next ? `${next.order === -1 ? '-' : ''}${next.columnKey}` : undefined,
                },
                hashParams
            )
        }
    }

    return [sorting, toggleSorting]
}
