import { useActions } from 'kea'
import { useEffect } from 'react'

import { inboxBulkActionsLogic } from '../logics/inboxBulkActionsLogic'
import { isTextEntryTarget } from '../utils/reportSelection'

/**
 * List side of the multi-select: tells the selection which rows are on screen and in what order,
 * so a shift-click ranges over the rendered list and stale ids are dropped when the list reloads
 * or the filters change. Esc clears the selection, and so does leaving the list.
 */
export function useSelectableReportList(orderedReportIds: string[]): void {
    const { setVisibleReportIds, clearSelection } = useActions(inboxBulkActionsLogic)

    // Keyed on the joined ids: the list rebuilds its row array on every render, and the array
    // identity alone would re-prune (and re-render every card) each time.
    const orderKey = orderedReportIds.join(',')
    useEffect(() => {
        setVisibleReportIds(orderKey === '' ? [] : orderKey.split(','))
    }, [orderKey, setVisibleReportIds])

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key !== 'Escape' || isTextEntryTarget(event.target)) {
                return
            }
            clearSelection()
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [clearSelection])

    // A selection means nothing on another tab or another scene.
    useEffect(() => clearSelection, [clearSelection])
}
