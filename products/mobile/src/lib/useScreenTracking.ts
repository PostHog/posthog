import { useGlobalSearchParams, useSegments } from 'expo-router'
import { useEffect, useRef } from 'react'

import { trackScreen } from './analytics'

function isGroup(segment: string): boolean {
    return segment.startsWith('(') && segment.endsWith(')')
}

/**
 * The route pattern without layout groups, such as `inbox`, `report/[id]` or `views/insight/[shortId]`. Dynamic
 * segments keep their bracket names, so one screen never splits into one name per id.
 */
export function screenName(segments: readonly string[]): string {
    const parts = segments.filter((segment) => !isGroup(segment))
    return parts.length > 0 ? parts.join('/') : 'index'
}

/** `report/[id]/index.tsx` loses its `index` segment, so the report keeps the `report/[id]` name. */
const REPORT_SCREENS: ReadonlySet<string> = new Set(['report/[id]', 'report/[id]/details'])

/** Sends one `$screen` per route change. Call it once, from the root layout. */
export function useScreenTracking(enabled: boolean): void {
    const segments = useSegments()
    const params = useGlobalSearchParams()
    const name = screenName(segments)
    const reportId = REPORT_SCREENS.has(name) && typeof params.id === 'string' ? params.id : undefined
    const last = useRef<string | null>(null)

    useEffect(() => {
        // `index` only redirects, so it is not a screen a person sees.
        if (!enabled || name === 'index') {
            return
        }
        // A report opened from another report keeps the name, so the id is part of the key.
        const key = `${name}|${reportId ?? ''}`
        if (last.current === key) {
            return
        }
        last.current = key
        trackScreen(name, reportId ? { report_id: reportId } : undefined)
    }, [enabled, name, reportId])
}
