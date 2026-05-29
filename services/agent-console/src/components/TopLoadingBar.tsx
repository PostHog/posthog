/**
 * `<TopLoadingBar />` — thin indeterminate progress bar fixed at the top
 * of the viewport that lights up whenever any `useResource` is in
 * flight. Sits in the AppShell so it survives navigation; the
 * pages themselves can render stale data underneath without flashing.
 *
 * A 150ms grace period suppresses the bar for very-fast fetches that
 * resolve within a frame or two — otherwise every navigation produces
 * a distracting flicker even when data was warm in cache.
 */

'use client'

import { useEffect, useState } from 'react'

import { useInFlightCount } from '@/lib/loadingIndicator'

const SHOW_AFTER_MS = 150

export function TopLoadingBar(): React.ReactElement | null {
    const count = useInFlightCount()
    const [visible, setVisible] = useState(false)

    useEffect(() => {
        if (count === 0) {
            setVisible(false)
            return
        }
        const t = setTimeout(() => setVisible(true), SHOW_AFTER_MS)
        return () => clearTimeout(t)
    }, [count])

    if (!visible) {
        return null
    }

    return (
        <div
            className="pointer-events-none fixed inset-x-0 top-0 z-[100] h-0.5 overflow-hidden bg-transparent"
            role="progressbar"
            aria-label="Loading"
        >
            <div className="animate-top-loading-bar h-full w-1/3 rounded-r-full bg-primary" />
        </div>
    )
}
