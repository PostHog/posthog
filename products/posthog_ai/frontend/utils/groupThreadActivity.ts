import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import { resolveToolCall } from './toolResolver'

export interface ThreadActivityGroup {
    id: string
    type: 'activity_group'
    items: ThreadItem[]
    startedAt?: number
    endedAt?: number
}

export type ThreadDisplayItem = ThreadItem | ThreadActivityGroup

/** Runs stay within the supplied page; hidden items must never make separate calls look adjacent. */
export function groupConsecutiveTools(
    items: ThreadItem[],
    toolInvocations: ReadonlyMap<string, ToolInvocation>
): ThreadItem[][] {
    const groups: ThreadItem[][] = []
    let previousKey: string | undefined
    for (const item of items) {
        const call =
            item.type === 'tool_invocation' && item.toolCallId ? toolInvocations.get(item.toolCallId) : undefined
        const resolved = call ? resolveToolCall(call) : undefined
        const key =
            call && resolved?.resolvedKey && resolved.resolvedKey !== '__posthog_exec_unknown__'
                ? JSON.stringify([call.rawServerName, resolved.resolvedKey])
                : undefined
        if (key && key === previousKey) {
            groups[groups.length - 1].push(item)
        } else {
            groups.push([item])
        }
        previousKey = key
    }
    return groups
}

export function groupThreadActivity(items: ThreadItem[], standaloneToolIds: ReadonlySet<string>): ThreadDisplayItem[] {
    const result: ThreadDisplayItem[] = []
    let group: ThreadActivityGroup | undefined
    for (const item of items) {
        const isActivity =
            item.type === 'assistant_thought' ||
            (item.type === 'task_notification' && item.status === 'completed') ||
            (item.type === 'tool_invocation' && !!item.toolCallId && !standaloneToolIds.has(item.toolCallId))
        if (!isActivity) {
            if (group && item.startedAt !== undefined) {
                group.endedAt = Math.max(group.endedAt ?? 0, item.startedAt)
            }
            group = undefined
            result.push(item)
            continue
        }
        if (!group) {
            group = { id: `activity-${item.id}`, type: 'activity_group', items: [], startedAt: item.startedAt }
            result.push(group)
        }
        group.items.push(item)
        // An imported/missing start makes the whole interval unknown, rather than a misleading zero.
        if (item.startedAt === undefined) {
            group.startedAt = undefined
        }
        if (item.endedAt !== undefined) {
            group.endedAt = Math.max(group.endedAt ?? 0, item.endedAt)
        }
    }
    return result
}

/** Groups over 10 items show the first 2 and last 3; the middle opens with one click. */
export const ACTIVITY_WINDOW_LIMIT = 10
/** Identical consecutive calls fold into one row only from this many, and only in the hidden middle. */
export const ACTIVITY_CHAIN_MIN = 3

export function activityWindow<T>(
    items: T[],
    showMiddle: boolean
): { first: T[]; middle: T[]; last: T[]; hiddenCount: number } {
    if (items.length <= ACTIVITY_WINDOW_LIMIT) {
        return { first: items, middle: [], last: [], hiddenCount: 0 }
    }
    return {
        first: items.slice(0, 2),
        middle: showMiddle ? items.slice(2, -3) : [],
        last: items.slice(-3),
        hiddenCount: items.length - 5,
    }
}
