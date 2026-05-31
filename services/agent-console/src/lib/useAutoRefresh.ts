/**
 * `useAutoRefresh` — call `resource.reload()` on a timer.
 *
 * Pauses when the tab is hidden (`document.visibilityState !== 'visible'`)
 * so backgrounded panels don't burn API calls. Resumes — with an
 * immediate refresh — when the tab comes back into focus.
 *
 * Designed to compose with `useResource`: pass the returned
 * `ResourceState` and an interval, drop a `<RefreshIndicator>` next
 * to the panel header. No copy-paste; one hook per panel.
 */

'use client'

import { useEffect } from 'react'

import type { ResourceState } from './useResource'

interface UseAutoRefreshOpts {
    /** Interval between background refreshes, in ms. */
    intervalMs: number
    /** Disable the timer without unmounting the hook. */
    paused?: boolean
}

export function useAutoRefresh<T>(
    resource: ResourceState<T>,
    { intervalMs, paused = false }: UseAutoRefreshOpts
): void {
    const reload = resource.reload
    useEffect(() => {
        if (paused || intervalMs <= 0) {
            return
        }
        if (typeof document === 'undefined' || typeof window === 'undefined') {
            return
        }
        let timerId: number | null = null
        const tick = (): void => {
            if (document.visibilityState === 'visible') {
                reload()
            }
        }
        const start = (): void => {
            stop()
            timerId = window.setInterval(tick, intervalMs)
        }
        const stop = (): void => {
            if (timerId !== null) {
                window.clearInterval(timerId)
                timerId = null
            }
        }
        const onVisibility = (): void => {
            if (document.visibilityState === 'visible') {
                // Fire immediately so the panel doesn't show stale data on resume.
                reload()
                start()
            } else {
                stop()
            }
        }
        if (document.visibilityState === 'visible') {
            start()
        }
        document.addEventListener('visibilitychange', onVisibility)
        return () => {
            stop()
            document.removeEventListener('visibilitychange', onVisibility)
        }
    }, [reload, intervalMs, paused])
}
