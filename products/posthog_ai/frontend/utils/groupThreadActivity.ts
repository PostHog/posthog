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

export function activityWindow<T>(
    items: T[],
    middlePage: number | null
): {
    first: T[]
    middle: T[]
    last: T[]
    hiddenCount: number
    pageCount: number
    page: number
} {
    const hiddenCount = items.length > 10 ? items.length - 5 : 0
    const pageCount = Math.ceil(hiddenCount / 10)
    const page = Math.max(0, Math.min(middlePage ?? 0, pageCount - 1))
    return {
        first: hiddenCount ? items.slice(0, 2) : items,
        middle:
            hiddenCount && middlePage !== null
                ? items.slice(2 + page * 10, Math.min(2 + (page + 1) * 10, items.length - 3))
                : [],
        last: hiddenCount ? items.slice(-3) : [],
        hiddenCount,
        pageCount,
        page,
    }
}
