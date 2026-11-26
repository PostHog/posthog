import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MetricGoalApi } from './generated/api.schemas'

export type GoalStatus = 'met' | 'on_track' | 'behind' | 'no_goal' | 'unmeasured'

const ON_TRACK_PROGRESS = 0.7

export const GOAL_STATUS_LABEL: Record<GoalStatus, string> = {
    met: 'Met',
    on_track: 'On track',
    behind: 'Behind',
    no_goal: 'No goal',
    unmeasured: 'No data',
}

export function goalProgress(value: number, goal: MetricGoalApi): number {
    if (goal.direction === 'at_most') {
        if (value <= goal.value) {
            return 1
        }
        return value <= 0 ? 0 : Math.max(0, Math.min(1, goal.value / value))
    }
    if (goal.value <= 0) {
        return value >= goal.value ? 1 : 0
    }
    return Math.max(0, Math.min(1, value / goal.value))
}

export function goalStatus(value: number | null, goal: MetricGoalApi | undefined): GoalStatus {
    if (!goal) {
        return 'no_goal'
    }
    if (value === null) {
        return 'unmeasured'
    }
    if (goal.direction === 'at_most' ? value <= goal.value : value >= goal.value) {
        return 'met'
    }
    return goalProgress(value, goal) >= ON_TRACK_PROGRESS ? 'on_track' : 'behind'
}

export function goalText(goal: MetricGoalApi): string {
    return `${goal.direction === 'at_most' ? 'At most' : 'At least'} ${humanFriendlyNumber(goal.value)}`
}
