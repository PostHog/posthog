import { useLayoutEffect, useState } from 'react'

export function useStickyColumnWidth(container: HTMLElement | null, fallback: number): number {
    const [measured, setMeasured] = useState(fallback)
    useLayoutEffect(() => {
        const cell = container?.querySelector<HTMLElement>('thead th')
        const width = cell ? Math.round(cell.getBoundingClientRect().width) : fallback
        if (width !== measured) {
            setMeasured(width)
        }
    })
    return measured
}
