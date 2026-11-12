import { dayjs } from 'lib/dayjs'
import { hasDeniedApprovalRequest, isSchedulePaused } from 'scenes/feature-flags/scheduleOccurrences'

import { isV1FeatureFlagConfig } from 'products/feature_flags/frontend/featureFlagConfigFormat'
import type {
    ActivityLogEntryApi,
    FeatureFlagApi,
    ScheduledChangeApi,
} from 'products/feature_flags/frontend/generated/api.schemas'

export interface RolloutStep {
    from: string
    to: string
    percent: number
    label: string
    upcoming?: boolean
}

interface RolloutGroup {
    properties?: unknown[] | null
    rollout_percentage?: number | null
}

interface RolloutFilters {
    groups?: RolloutGroup[] | null
    early_exit?: boolean
    feature_enrollment?: boolean
    holdout?: { exclusion_percentage?: number } | null
}

interface RolloutState {
    active: boolean
    filters: RolloutFilters
}

const isOpen = (group: RolloutGroup): boolean => !group.properties?.length
const rolloutOf = (group: RolloutGroup): number => group.rollout_percentage ?? 100

function reachOf(filters: RolloutFilters): { percent: number; targeted: boolean } | null {
    const groups = filters.groups ?? []
    if (filters.early_exit) {
        const first = groups[0]
        return first ? { percent: rolloutOf(first), targeted: !isOpen(first) } : null
    }
    const open = groups.filter(isOpen)
    if (open.length) {
        return { percent: Math.max(...open.map(rolloutOf)), targeted: false }
    }
    return groups.length ? { percent: Math.max(...groups.map(rolloutOf)), targeted: true } : null
}

function audienceOf(state: RolloutState): { percent: number; label: string } {
    if (!state.active) {
        return { percent: 0, label: 'Off' }
    }
    const reach = reachOf(state.filters)
    if (!reach) {
        return state.filters.feature_enrollment ? { percent: 0, label: 'Opt-in only' } : { percent: 0, label: 'No one' }
    }
    const holdout = state.filters.holdout?.exclusion_percentage ?? 0
    const percent = Math.round(reach.percent * (100 - holdout)) / 100
    const optIn = state.filters.feature_enrollment ? ' + opt-in' : ''
    if (reach.targeted) {
        const label = percent === 100 ? 'Targeted' : `Targeted, ${percent}%`
        return { percent: Math.max(percent / 4, 8), label: `${label}${optIn}` }
    }
    return { percent, label: percent === 100 && !optIn ? 'Everyone' : `${percent}%${optIn}` }
}

function groupsOf(filters: unknown): RolloutGroup[] {
    const groups = filtersOf(filters).groups
    return Array.isArray(groups) ? groups.filter((group) => group && typeof group === 'object') : []
}

function filtersOf(filters: unknown): RolloutFilters {
    return (filters ?? {}) as RolloutFilters
}

const isV1 = (filters: unknown): boolean => !filters || isV1FeatureFlagConfig(filters as never)

function changeOf(entry: ActivityLogEntryApi, field: string): { before: unknown; after: unknown } | undefined {
    return entry.detail?.changes?.find((change) => change.field === field)
}

export function rolloutSteps(
    flag: FeatureFlagApi,
    activity: ActivityLogEntryApi[],
    scheduled: ScheduledChangeApi[],
    today: dayjs.Dayjs,
    horizon: dayjs.Dayjs
): RolloutStep[] {
    const updates = activity
        .filter((entry) => entry.activity === 'updated' && (changeOf(entry, 'filters') || changeOf(entry, 'active')))
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
    const firstFilters = updates.map((entry) => changeOf(entry, 'filters')).find(Boolean)
    const firstActive = updates.map((entry) => changeOf(entry, 'active')).find(Boolean)
    let state: RolloutState = {
        active: firstActive ? Boolean(firstActive.before) : !!flag.active,
        filters: filtersOf(firstFilters ? firstFilters.before : flag.filters),
    }
    const points: { at: string; state: RolloutState; upcoming?: boolean }[] = [{ at: flag.created_at, state }]
    for (const entry of updates) {
        const filters = changeOf(entry, 'filters')
        const active = changeOf(entry, 'active')
        state = {
            active: active ? Boolean(active.after) : state.active,
            filters: filters ? filtersOf(filters.after) : state.filters,
        }
        points.push({ at: entry.created_at, state })
    }
    const current: RolloutState = { active: !!flag.active, filters: filtersOf(flag.filters) }
    points.push({ at: today.toISOString(), state: current })
    const pending = scheduled
        .filter(
            (change) =>
                change.record_id === String(flag.id) &&
                !change.executed_at &&
                !change.is_recurring &&
                !isSchedulePaused(change as never) &&
                !hasDeniedApprovalRequest(change as never) &&
                !(change.end_date && dayjs(change.end_date).isBefore(today))
        )
        .sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at))
    state = current
    for (const change of pending) {
        const payload = (change.payload ?? {}) as { operation?: string; value?: unknown }
        if (payload.operation === 'update_status') {
            state = { ...state, active: Boolean(payload.value) }
        } else if (payload.operation === 'add_release_condition' && groupsOf(payload.value).length) {
            state = {
                ...state,
                filters: {
                    ...state.filters,
                    groups: [...(state.filters.groups ?? []), ...groupsOf(payload.value)],
                },
            }
        } else {
            continue
        }
        points.push({ at: change.scheduled_at, state, upcoming: true })
    }
    if (!points.every((point) => isV1(point.state.filters))) {
        return []
    }
    const steps: RolloutStep[] = []
    points.forEach((point, index) => {
        const next = points[index + 1]
        const to =
            next && !(next.upcoming && !point.upcoming)
                ? next.at
                : point.upcoming
                  ? horizon.toISOString()
                  : today.toISOString()
        const { percent, label } = audienceOf(point.state)
        const last = steps[steps.length - 1]
        if (last && last.label === label && !!last.upcoming === !!point.upcoming) {
            last.to = to
        } else if (dayjs(to).isAfter(dayjs(point.at)) || !next) {
            steps.push({ from: point.at, to, percent, label, upcoming: point.upcoming })
        }
    })
    return steps
}
