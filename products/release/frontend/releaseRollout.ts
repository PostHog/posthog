import { dayjs } from 'lib/dayjs'

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

interface RolloutState {
    active: boolean
    groups: RolloutGroup[]
}

function audienceOf(state: RolloutState): { percent: number; label: string } {
    if (!state.active) {
        return { percent: 0, label: 'Off' }
    }
    const open = state.groups.filter((group) => !group.properties?.length)
    if (open.length) {
        const percent = Math.max(...open.map((group) => group.rollout_percentage ?? 100))
        return { percent, label: percent === 100 ? 'Everyone' : `${percent}%` }
    }
    if (state.groups.length) {
        const percent = Math.max(...state.groups.map((group) => group.rollout_percentage ?? 100))
        return { percent: Math.max(percent / 4, 8), label: percent === 100 ? 'Targeted' : `Targeted, ${percent}%` }
    }
    return { percent: 0, label: 'No one' }
}

function groupsOf(filters: unknown): RolloutGroup[] {
    return ((filters as { groups?: RolloutGroup[] } | null)?.groups ?? []) as RolloutGroup[]
}

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
        groups: firstFilters ? groupsOf(firstFilters.before) : groupsOf(flag.filters),
    }
    const points: { at: string; state: RolloutState; upcoming?: boolean }[] = [{ at: flag.created_at, state }]
    for (const entry of updates) {
        const filters = changeOf(entry, 'filters')
        const active = changeOf(entry, 'active')
        state = {
            active: active ? Boolean(active.after) : state.active,
            groups: filters ? groupsOf(filters.after) : state.groups,
        }
        points.push({ at: entry.created_at, state })
    }
    const current: RolloutState = { active: !!flag.active, groups: groupsOf(flag.filters) }
    points.push({ at: today.toISOString(), state: current })
    const pending = scheduled
        .filter((change) => !change.executed_at && change.record_id === String(flag.id))
        .sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at))
    state = current
    for (const change of pending) {
        const payload = (change.payload ?? {}) as { operation?: string; value?: unknown }
        if (payload.operation === 'update_status') {
            state = { ...state, active: Boolean(payload.value) }
        } else if (payload.operation === 'add_release_condition') {
            state = { ...state, groups: [...state.groups, ...groupsOf(payload.value)] }
        } else {
            continue
        }
        points.push({ at: change.scheduled_at, state, upcoming: true })
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
