import { RefObject, useLayoutEffect, useRef, useState } from 'react'

/**
 * Measures the header cells of the sticky columns, so each one sticks right after the sticky columns before it.
 * Header cells name their column with `data-column-key`.
 */
export function useStickyColumnOffsets(
    stickyKeys: string[],
    columnKeys: string[]
): { headerRowRef: RefObject<HTMLTableRowElement>; offsets: Record<string, number> } {
    const headerRowRef = useRef<HTMLTableRowElement>(null)
    const [offsets, setOffsets] = useState<Record<string, number>>({})
    const stickySignature = JSON.stringify(stickyKeys)
    const columnSignature = JSON.stringify(columnKeys)

    useLayoutEffect(() => {
        const row = headerRowRef.current
        if (!row) {
            return
        }
        const sticky = new Set<string>(JSON.parse(stickySignature))
        const measure = (): void => {
            const next: Record<string, number> = {}
            let left = 0
            for (const cell of Array.from(row.children) as HTMLElement[]) {
                const key = cell.dataset.columnKey
                if (key && sticky.has(key)) {
                    next[key] = left
                    left += cell.getBoundingClientRect().width
                }
            }
            setOffsets((previous) =>
                Object.keys(next).length === Object.keys(previous).length &&
                Object.entries(next).every(([key, value]) => previous[key] === value)
                    ? previous
                    : next
            )
        }
        measure()
        const observer = new ResizeObserver(measure)
        for (const cell of Array.from(row.children)) {
            observer.observe(cell)
        }
        return () => observer.disconnect()
    }, [stickySignature, columnSignature])

    return { headerRowRef, offsets }
}
