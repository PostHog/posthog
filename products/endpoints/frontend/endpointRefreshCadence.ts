import { humanFriendlyDuration } from 'lib/utils/durations'
import { CADENCE_LABELS, SyncFrequencySelectProps } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import { DataModelingSyncInterval } from '~/types'

export type EndpointSyncFrequencyBounds = NonNullable<SyncFrequencySelectProps['bounds']>

/**
 * The data freshness values the API accepts, each with the cadence the materialized view runs at.
 * Mirrors DATA_FRESHNESS_BUCKET_SPECS in products/endpoints/backend/constants.py: the API rejects any
 * other number of seconds, so the picker offers these and nothing else.
 */
export const ENDPOINT_REFRESH_CADENCES: { seconds: number; cadence: DataModelingSyncInterval }[] = [
    { seconds: 900, cadence: '15min' },
    { seconds: 1800, cadence: '30min' },
    { seconds: 3600, cadence: '1hour' },
    { seconds: 21600, cadence: '6hour' },
    { seconds: 43200, cadence: '12hour' },
    { seconds: 86400, cadence: '24hour' },
    { seconds: 604800, cadence: '7day' },
]

export function cadenceForDataFreshness(seconds: number | null | undefined): DataModelingSyncInterval | null {
    return ENDPOINT_REFRESH_CADENCES.find((bucket) => bucket.seconds === seconds)?.cadence ?? null
}

export function dataFreshnessForCadence(cadence: DataModelingSyncInterval): number | null {
    return ENDPOINT_REFRESH_CADENCES.find((bucket) => bucket.cadence === cadence)?.seconds ?? null
}

/**
 * The cadence bounds of an endpoint, in the shape the materialized view picker reads. An endpoint has
 * no upstream or downstream bound, only the plan's refresh floor, so every cadence below the floor is
 * blocked by the plan and the rest are allowed.
 */
export function endpointSyncFrequencyBounds(planRefreshFloorSeconds: number | null): EndpointSyncFrequencyBounds {
    const floorBucket =
        planRefreshFloorSeconds === null
            ? null
            : (ENDPOINT_REFRESH_CADENCES.find((bucket) => bucket.seconds >= planRefreshFloorSeconds) ?? null)
    const planFloorLabel =
        planRefreshFloorSeconds === null
            ? null
            : floorBucket
              ? CADENCE_LABELS[floorBucket.cadence]
              : humanFriendlyDuration(planRefreshFloorSeconds)

    return {
        frequency_mode: 'tiered',
        options: ENDPOINT_REFRESH_CADENCES.map(({ seconds, cadence }) => {
            const allowed = planRefreshFloorSeconds === null || seconds >= planRefreshFloorSeconds
            return {
                cadence,
                allowed,
                blocked_by: allowed ? null : 'plan',
                blocker: null,
                speeds_up: [],
                speeds_up_withheld: false,
            }
        }),
        floor: null,
        plan_floor: planFloorLabel ? { label: planFloorLabel, blocker: null } : null,
        ceiling: null,
        best_effort_sources: [],
        best_effort_sources_withheld: false,
    }
}
