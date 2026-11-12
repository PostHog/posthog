import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releaseCalendarLogic } from './releaseCalendarLogic'

export function useRefreshChangedFlagHistory(flags: FeatureFlagApi[]): void {
    const { refreshFlagActivity } = useActions(releaseCalendarLogic)
    const seenVersions = useRef(new Map<number, string | null>())

    useEffect(() => {
        const changed: number[] = []
        for (const flag of flags) {
            const seen = seenVersions.current.get(flag.id)
            if (seen !== undefined && seen !== flag.updated_at) {
                changed.push(flag.id)
            }
            seenVersions.current.set(flag.id, flag.updated_at)
        }
        if (changed.length) {
            refreshFlagActivity(changed)
        }
    }, [flags, refreshFlagActivity])
}
