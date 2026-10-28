import { RefObject, useEffect, useRef } from 'react'

function focusWasLost(): boolean {
    return !document.activeElement || document.activeElement === document.body
}

export function useFocusFollowsRemovedRow(
    containerRef: RefObject<HTMLElement>,
    rowIds: string[],
    focusWhenEmpty: () => void
): void {
    const previousRowIds = useRef(rowIds)

    useEffect(() => {
        const previous = previousRowIds.current
        previousRowIds.current = rowIds
        const removedIndex = previous.findIndex((id) => !rowIds.includes(id))
        if (removedIndex < 0 || !focusWasLost()) {
            return
        }
        const nextId = rowIds[removedIndex] ?? rowIds[removedIndex - 1]
        if (!nextId) {
            focusWhenEmpty()
            return
        }
        containerRef.current
            ?.querySelector<HTMLElement>(`[data-suggestion-row="${nextId}"] [data-suggestion-actions] button`)
            ?.focus()
    }, [rowIds, containerRef, focusWhenEmpty])
}
