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

const STARTUP_STATUSES = new Set(['sdk_initialization', 'setup_hooks'])
const LONG_RUNNING_STATUSES = new Set(['compacting', 'clearing'])

export function isStartupStatus(item: ThreadDisplayItem): boolean {
    return item.type === 'status' && STARTUP_STATUSES.has(item.status ?? '')
}

export function isRunningStatus(item: ThreadDisplayItem): boolean {
    return item.type === 'status' && !item.isComplete && LONG_RUNNING_STATUSES.has(item.status ?? '')
}

export interface ToolRunOptions {
    pinnedToolIds: ReadonlySet<string>
    widgetToolIds: ReadonlySet<string>
    /** Nothing more can join the thread's last run, because the turn finished or the run stopped. */
    settled: boolean
}

const isToolCall = (item: ThreadItem): boolean => item.type === 'tool_invocation' && !!item.toolCallId

/** Thoughts and finished task notifications narrate a run, so they join it and never break it. */
const ridesAlong = (item: ThreadItem): boolean =>
    item.type === 'assistant_thought' || (item.type === 'task_notification' && item.status === 'completed')

/**
 * PostHog Desktop's grouping: two or more tool calls fold into a group, and a lone call keeps its row. A
 * closed run's last call keeps its row when it is a finished widget, so the chart the agent talks about stays
 * visible. The trailing run closes only once `settled`, so its chart cannot appear and then fold again.
 */
export function groupToolRuns(
    items: ThreadItem[],
    toolInvocations: ReadonlyMap<string, ToolInvocation>,
    { pinnedToolIds, widgetToolIds, settled }: ToolRunOptions
): ThreadDisplayItem[] {
    const finalWidgetIds = new Set<string>()
    let runLastCall: string | undefined
    const closeRun = (): void => {
        if (runLastCall && widgetToolIds.has(runLastCall) && toolInvocations.get(runLastCall)?.status === 'completed') {
            finalWidgetIds.add(runLastCall)
        }
        runLastCall = undefined
    }
    for (const item of items) {
        if (isToolCall(item) && !pinnedToolIds.has(item.toolCallId!)) {
            runLastCall = item.toolCallId
        } else if (!ridesAlong(item)) {
            closeRun()
        }
    }
    if (settled) {
        closeRun()
    }

    const result: ThreadDisplayItem[] = []
    let run: ThreadItem[] = []
    const flush = (): void => {
        const calls = run.filter(isToolCall)
        if (calls.length >= 2 || calls.some((call) => widgetToolIds.has(call.toolCallId!))) {
            result.push({ id: `activity-${calls[0].id}`, type: 'activity_group', items: run })
        } else {
            result.push(...run)
        }
        run = []
    }
    for (const item of items) {
        const folds = isToolCall(item)
            ? !pinnedToolIds.has(item.toolCallId!) && !finalWidgetIds.has(item.toolCallId!)
            : ridesAlong(item)
        if (folds) {
            run.push(item)
            continue
        }
        flush()
        // The phases flip while setup hooks run; the row shows only the latest one.
        if (isStartupStatus(item) && result.length > 0 && isStartupStatus(result[result.length - 1])) {
            result[result.length - 1] = item
        } else {
            result.push(item)
        }
    }
    flush()
    return result
}

export function reuseActivityGroups(previous: ThreadDisplayItem[], next: ThreadDisplayItem[]): ThreadDisplayItem[] {
    const previousGroups = new Map<string, ThreadActivityGroup>()
    const groupOfMember = new Map<string, string>()
    for (const item of previous) {
        if (item.type === 'activity_group') {
            previousGroups.set(item.id, item)
            item.items.forEach((row) => groupOfMember.set(row.id, item.id))
        }
    }
    if (previousGroups.size === 0) {
        return next
    }
    // A group's id comes from its first member, so earlier calls that load in front of it would rename it and
    // remount it. A group that shares a member with a previous group keeps that group's id, unless a group in
    // `next` already has that id, so a group that splits never gives two groups one key.
    const reserved = new Set(
        next.flatMap((item) => (item.type === 'activity_group' && previousGroups.has(item.id) ? [item.id] : []))
    )
    const claimed = new Set<string>()
    return next.map((nextItem) => {
        if (nextItem.type !== 'activity_group') {
            return nextItem
        }
        const carried = previousGroups.has(nextItem.id)
            ? undefined
            : nextItem.items
                  .map((row) => groupOfMember.get(row.id))
                  .find((id) => id !== undefined && !claimed.has(id) && !reserved.has(id))
        const item = carried ? { ...nextItem, id: carried } : nextItem
        claimed.add(item.id)
        const old = previousGroups.get(item.id)
        return old &&
            old.startedAt === item.startedAt &&
            old.endedAt === item.endedAt &&
            old.items.length === item.items.length &&
            old.items.every((row, index) => row === item.items[index])
            ? old
            : item
    })
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
