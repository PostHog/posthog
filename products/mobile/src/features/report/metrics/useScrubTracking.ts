import { useCallback, useRef } from 'react'

import type { ChartPoint } from '@/ui/chart/types'

/** An `onSelect` handler that calls `onScrubStart` once per touch: on the first point after a release. */
export function useScrubTracking(onScrubStart: () => void): (point: ChartPoint | null) => void {
    const scrubbing = useRef(false)
    const latest = useRef(onScrubStart)
    latest.current = onScrubStart
    return useCallback((point: ChartPoint | null): void => {
        if (point === null) {
            scrubbing.current = false
            return
        }
        if (!scrubbing.current) {
            scrubbing.current = true
            latest.current()
        }
    }, [])
}
