import {
    type AcpMessage,
    isJsonRpcNotification,
    isJsonRpcResponse,
    type JsonRpcMessage,
    type Plan,
    type PlanEntry,
    type SessionNotification,
} from './acp-types'
import { isNotification, POSTHOG_NOTIFICATIONS } from './lib/acpExtensions'

export interface PlanStats {
    completed: number
    total: number
    inProgress: PlanEntry | undefined
    allCompleted: boolean
}

/**
 * A turn ends either with a JSON-RPC prompt response carrying a `stopReason`
 * (local runs) or a `_posthog/turn_complete` notification (cloud runs).
 */
function isTurnEnd(msg: JsonRpcMessage): boolean {
    if (isJsonRpcResponse(msg)) {
        return (msg.result as { stopReason?: string } | undefined)?.stopReason !== undefined
    }
    return isJsonRpcNotification(msg) && isNotification(msg.method, POSTHOG_NOTIFICATIONS.TURN_COMPLETE)
}

/**
 * Latest `plan` session update from the in-progress turn, or null. Mirrors the
 * reference app's `latestPlan` memo in SessionView: a plan is only "live" while
 * its turn is still running — once a turn-end signal appears after the plan,
 * the plan is stale and should not be shown.
 */
export function derivePlan(events: AcpMessage[]): Plan | null {
    let planIndex = -1
    let plan: Plan | null = null
    let turnEndIndex = -1

    for (let i = events.length - 1; i >= 0; i--) {
        const msg = events[i].message

        if (turnEndIndex === -1 && isTurnEnd(msg)) {
            turnEndIndex = i
        }

        if (planIndex === -1 && isJsonRpcNotification(msg) && msg.method === 'session/update') {
            const update = (msg.params as SessionNotification | undefined)?.update
            if (update?.sessionUpdate === 'plan') {
                planIndex = i
                plan = update.entries?.length ? update : null
            }
        }

        if (planIndex !== -1 && turnEndIndex !== -1) {
            break
        }
    }

    if (turnEndIndex > planIndex) {
        return null
    }
    return plan
}

export function getPlanStats(plan: Plan): PlanStats {
    const entries = plan.entries ?? []
    const completed = entries.filter((entry) => entry.status === 'completed').length
    const total = entries.length
    const inProgress = entries.find((entry) => entry.status === 'in_progress')
    return { completed, total, inProgress, allCompleted: completed === total }
}
