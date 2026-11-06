import type { LemonTagType } from '@posthog/lemon-ui'

import type {
    GoalScoutEntryApi,
    GoalScoutStatusEnumApi,
    GoalScoutWorkApi,
} from 'products/signals/frontend/generated/api.schemas'

import type { ScoutGroupKey, ScoutRosterRow } from '../scoutGroups'

export const GOAL_STATUS_LABELS: Record<GoalScoutStatusEnumApi, string> = {
    setting_up: 'Setting up',
    running: 'Running',
    paused: 'Paused',
    reached: 'Goal reached',
    spent: 'Budget used',
    closed: 'Closed',
}

export const OUTCOME_LABELS: Record<string, string> = {
    won: 'Won',
    lost: 'Lost',
    flat: 'No clear effect',
    harmed: 'Guardrail got worse',
    broken: 'Broken test',
    dropped: 'Dropped',
}

const OUTCOME_TAGS: Record<string, LemonTagType> = {
    won: 'success',
    lost: 'danger',
    harmed: 'danger',
    flat: 'muted',
    broken: 'warning',
    dropped: 'muted',
}

export interface GoalRosterSections {
    openGoals: ScoutRosterRow[]
    closedGoals: ScoutRosterRow[]
    scouts: ScoutRosterRow[]
}

export interface WorkStatus {
    label: string
    tag: LemonTagType
}

export function isLive(goal: Pick<GoalScoutEntryApi, 'status'>): boolean {
    return goal.status === 'setting_up' || goal.status === 'running'
}

export function goalRank(goal: GoalScoutEntryApi): number {
    if (goal.state.needs_you) {
        return 0
    }
    if (isLive(goal)) {
        return 1
    }
    return goal.status === 'closed' ? 3 : 2
}

export interface GoalDot {
    group: ScoutGroupKey
    tooltip: string
    className?: string
}

export function goalDot(goal: GoalScoutEntryApi): GoalDot {
    if (goal.state.needs_you) {
        return { group: 'needs_you', tooltip: 'Needs you', className: 'bg-warning' }
    }
    const tooltip = GOAL_STATUS_LABELS[goal.status]
    if (isLive(goal)) {
        return { group: 'working', tooltip }
    }
    if (goal.status === 'reached') {
        return { group: 'settling_in', tooltip }
    }
    return { group: 'off', tooltip, className: 'border-primary' }
}

const OUTCOME_TONES: Record<string, { bar: string; text: string }> = {
    won: { bar: 'bg-success', text: 'text-success' },
    lost: { bar: 'bg-danger', text: 'text-danger' },
    harmed: { bar: 'bg-danger', text: 'text-danger' },
}

export function outcomeTone(outcome: string): { bar: string; text: string } {
    return OUTCOME_TONES[outcome] ?? { bar: 'bg-muted', text: 'text-primary' }
}

export function effectBounds(item: GoalScoutWorkApi): [number, number] | null {
    const variant = item.result.variant && item.result.variant !== 'control' ? item.result.variant : 'test'
    const bounds = item.result.primary?.[variant]
    return bounds?.length === 2 && bounds[0] !== null && bounds[1] !== null ? [bounds[0], bounds[1]] : null
}

export function exposedPeople(item: GoalScoutWorkApi): number {
    return Object.values(item.result.exposures ?? {}).reduce((total, value) => total + value, 0)
}

export function isOpen(item: GoalScoutWorkApi): boolean {
    return ['building', 'review', 'live', 'stuck'].includes(item.stage)
}

export function taskRunning(item: Pick<GoalScoutWorkApi, 'task_status'>): boolean {
    return ['queued', 'in_progress'].includes(item.task_status)
}

export function taskFailed(item: Pick<GoalScoutWorkApi, 'task_status'>): boolean {
    return ['failed', 'cancelled'].includes(item.task_status)
}

export function workStatus(item: GoalScoutWorkApi): WorkStatus {
    switch (item.stage) {
        case 'building':
            return taskRunning(item) ? { label: 'Working', tag: 'primary' } : { label: 'Starting', tag: 'default' }
        case 'review':
            return { label: 'In review', tag: 'warning' }
        case 'live':
            return { label: 'Live', tag: 'primary' }
        case 'done':
            if (item.kind === 'tracking') {
                return { label: 'Checked', tag: 'success' }
            }
            return { label: OUTCOME_LABELS[item.outcome] || 'Learned', tag: OUTCOME_TAGS[item.outcome] ?? 'success' }
        case 'dropped':
            return { label: 'Dropped', tag: 'muted' }
        default:
            return { label: 'Needs attention', tag: 'warning' }
    }
}
