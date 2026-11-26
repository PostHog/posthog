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
    // Rows can leave the list, such as a confirmed competitor, so the page in state may now be past the last one.
    const page = pageSize ? Math.min(autoPage, Math.max(1, Math.ceil(rowCount / pageSize))) : 1
    return {
        show: !!pagination && rowCount > pageSize,
        page,
        pageSize,
        entryCount: rowCount,
        canGoBack: page > 1,
        canGoForward: page * pageSize < rowCount,
        slice: pageSize ? [(page - 1) * pageSize, page * pageSize] : null,
    }
}
