import { useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { dayjs } from 'lib/dayjs'

import type {
    ActivityLogEntryApi,
    FeatureFlagApi,
    ScheduledChangeApi,
} from 'products/feature_flags/frontend/generated/api.schemas'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { releaseLogic } from './releaseLogic'
import { RolloutStep, rolloutSteps } from './releaseRollout'

interface CachedSteps {
    flag: FeatureFlagApi
    activity: ActivityLogEntryApi[]
    scheduled: ScheduledChangeApi[]
    horizon: number
    steps: RolloutStep[]
}

export function useRolloutStepsByFlag(horizonDays: number): Map<number, RolloutStep[]> {
    const { flags, scheduledChanges } = useValues(releaseLogic)
    const { flagActivity } = useValues(releaseCalendarLogic)
    const cache = useRef(new Map<number, CachedSteps>())

    return useMemo(() => {
        const today = dayjs()
        const horizon = today.startOf('day').add(horizonDays, 'day')
        const steps = new Map<number, RolloutStep[]>()
        for (const flag of flags) {
            const activity = flagActivity[flag.id]
            if (!activity) {
                continue
            }
            const cached = cache.current.get(flag.id)
            if (
                cached?.flag === flag &&
                cached.activity === activity &&
                cached.scheduled === scheduledChanges &&
                cached.horizon === horizonDays
            ) {
                steps.set(flag.id, cached.steps)
                continue
            }
            const fresh = rolloutSteps(flag, activity, scheduledChanges, today, horizon)
            cache.current.set(flag.id, {
                flag,
                activity,
                scheduled: scheduledChanges,
                horizon: horizonDays,
                steps: fresh,
            })
            steps.set(flag.id, fresh)
        }
        return steps
    }, [flags, flagActivity, scheduledChanges, horizonDays])
}
