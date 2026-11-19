import { useFocusEffect } from 'expo-router'
import { useCallback, useRef, useState } from 'react'

/**
 * Numbers the visits of a screen, from 1. A tab stays mounted, so it counts one more visit each time it regains focus.
 * A pushed screen mounts once per visit, so it stays at 1.
 */
export function useTabVisit(tab: boolean): number {
    const [visit, setVisit] = useState(1)
    const seen = useRef(false)
    useFocusEffect(
        useCallback(() => {
            if (seen.current && tab) {
                setVisit((count) => count + 1)
            }
            seen.current = true
        }, [tab])
    )
    return visit
}
