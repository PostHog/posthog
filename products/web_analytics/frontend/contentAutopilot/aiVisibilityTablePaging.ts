import type { LemonTableProps } from 'lib/lemon-ui/LemonTable'

export interface PagerState {
    show: boolean
    page: number
    pageSize: number
    entryCount: number
    canGoBack: boolean
    canGoForward: boolean
    slice: [number, number] | null
}

/** Where a table is in its pages. A controlled pager comes from the caller; otherwise a page size
 * splits the rows on the client, as the Lemon table does. */
export function pagerState(
    pagination: LemonTableProps<any>['pagination'],
    autoPage: number,
    rowCount: number
): PagerState {
    const pageSize = pagination?.pageSize ?? 0
    if (pagination?.controlled) {
        const page = pagination.currentPage ?? 1
        const entryCount = pagination.entryCount ?? 0
        return {
            show: entryCount > pageSize,
            page,
            pageSize,
            entryCount,
            canGoBack: !!pagination.onBackward && page > 1,
            canGoForward: !!pagination.onForward,
            slice: null,
        }
    }
    return {
        show: !!pagination && rowCount > pageSize,
        page: autoPage,
        pageSize,
        entryCount: rowCount,
        canGoBack: autoPage > 1,
        canGoForward: autoPage * pageSize < rowCount,
        slice: pagination?.pageSize ? [(autoPage - 1) * pageSize, autoPage * pageSize] : null,
    }
}
