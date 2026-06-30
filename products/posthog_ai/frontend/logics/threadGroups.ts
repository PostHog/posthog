/**
 * Folds a flat run of tool-call work into collapsible groups — the "tool-call accordion" behavior.
 *
 * Ported from PostHog Code's `buildThreadGroups` / `conversationThreadConfig`. A group is a *maximal
 * consecutive run* of groupable items (tool calls + the reasoning thoughts between them); anything
 * else (a human message, direct assistant prose, an error, a status / progress / compaction marker,
 * a turn separator) flushes the run into a standalone row. Grouping is keyed on item type alone, so a
 * run never spans a turn boundary here — the separator flushes it.
 *
 * Pure and deterministic: safe to run inside a kea selector on every projection. Completed-turn
 * summaries are memoized by reference so a streamed token doesn't re-walk frozen groups.
 */

import { extractClaudeToolName } from '../components/tool/toolResolver'
import type { ThreadItem, ToolInvocation } from '../types/streamTypes'

/** How aggressively completed turns collapse into a tool-call group chip. */
export type CollapseMode = 'all' | 'partial' | 'none'

/** The in-flight turn streams expanded; completed turns collapse to a summary chip. */
export const COLLAPSE_MODE_DEFAULT: CollapseMode = 'partial'

export const grouping = {
    /** Tool names (SDK `_meta.claudeCode.toolName`) that spawn a subagent — counted separately. */
    subagentToolNames: new Set<string>(['Task', 'Agent']),
    /** Max distinct tool icons shown in a collapsed chip's icon strip. */
    maxIconsInChip: 10,
} as const

/** Per-action tallies for a collapsed group. */
export interface GroupCounts {
    execute: number
    read: number
    edit: number
    delete: number
    move: number
    search: number
    fetch: number
    subagents: number
    other: number
}

/** The closed set of icon keys a chip can carry; mapped to icon components in the chip component. */
export type GroupIconKey = 'subagent' | `kind:${string}`

export interface GroupSummary {
    counts: GroupCounts
    /** Distinct icon keys (deduped, capped at `maxIconsInChip`), in first-seen order. */
    icons: GroupIconKey[]
    /** Title of the most recent tool — "what's happening now" while running. */
    liveLabel: string | null
    /** Verb-led summary shown once the turn completes (e.g. "Ran 3 commands, read a file"). */
    doneLabel: string
    /** This group's last tool call is still pending/in_progress (drives the chip spinner). */
    active: boolean
    /** The group did countable tool work — lets the chip show the summary without the "Worked" fallback. */
    hasCountableWork: boolean
}

/**
 * One rendered row of the thread: either a passthrough item or a collapsed tool-call group standing
 * in for a run of work items.
 */
export type ThreadRow =
    | { kind: 'item'; id: string; item: ThreadItem }
    | {
          kind: 'tool_group'
          id: string
          items: ThreadItem[]
          summary: GroupSummary
          turnComplete: boolean
          expanded: boolean
      }

/** Whether an item folds into a tool-call group rather than getting its own row. */
export function isGroupableItem(item: ThreadItem): boolean {
    return item.type === 'tool_invocation' || item.type === 'assistant_thought'
}

function plural(n: number, singular: string, pluralForm: string): string {
    return `${n} ${n === 1 ? singular : pluralForm}`
}

function files(n: number): string {
    return n === 1 ? 'a file' : `${n} files`
}

/** Verb-led "done" summary, e.g. "Ran 25 commands, read a file, edited a file". */
export function buildDoneLabel(counts: GroupCounts): string {
    const seg: string[] = []
    if (counts.execute > 0) {
        seg.push(`ran ${plural(counts.execute, 'command', 'commands')}`)
    }
    if (counts.read > 0) {
        seg.push(`read ${files(counts.read)}`)
    }
    if (counts.edit > 0) {
        seg.push(`edited ${files(counts.edit)}`)
    }
    if (counts.delete > 0) {
        seg.push(`deleted ${files(counts.delete)}`)
    }
    if (counts.move > 0) {
        seg.push(`moved ${files(counts.move)}`)
    }
    if (counts.search > 0) {
        seg.push(`ran ${plural(counts.search, 'search', 'searches')}`)
    }
    if (counts.fetch > 0) {
        seg.push(`fetched ${plural(counts.fetch, 'page', 'pages')}`)
    }
    if (counts.subagents > 0) {
        seg.push(`spawned ${plural(counts.subagents, 'subagent', 'subagents')}`)
    }
    if (counts.other > 0) {
        seg.push(`ran ${plural(counts.other, 'tool call', 'tool calls')}`)
    }
    if (seg.length === 0) {
        return 'Worked'
    }
    const joined = seg.join(', ')
    return joined.charAt(0).toUpperCase() + joined.slice(1)
}

function summarize(items: ThreadItem[], invocations: Map<string, ToolInvocation>): GroupSummary {
    const counts: GroupCounts = {
        execute: 0,
        read: 0,
        edit: 0,
        delete: 0,
        move: 0,
        search: 0,
        fetch: 0,
        subagents: 0,
        other: 0,
    }
    let liveLabel: string | null = null
    let lastToolStatus: ToolInvocation['status'] | undefined
    const icons: GroupIconKey[] = []
    const seen = new Set<GroupIconKey>()

    const addIcon = (key: GroupIconKey): void => {
        if (seen.has(key) || icons.length >= grouping.maxIconsInChip) {
            return
        }
        seen.add(key)
        icons.push(key)
    }

    for (const item of items) {
        if (item.type !== 'tool_invocation' || !item.toolCallId) {
            continue
        }
        const invocation = invocations.get(item.toolCallId)
        if (!invocation) {
            continue
        }
        // Most recent tool's title — what the chip shows while still running.
        if (invocation.title) {
            liveLabel = invocation.title
        }
        lastToolStatus = invocation.status
        const claudeToolName = extractClaudeToolName(invocation.meta)
        if (claudeToolName && grouping.subagentToolNames.has(claudeToolName)) {
            counts.subagents++
            addIcon('subagent')
            continue
        }
        const kind = invocation.kind ?? null
        switch (kind) {
            case 'execute':
                counts.execute++
                break
            case 'read':
                counts.read++
                break
            case 'edit':
                counts.edit++
                break
            case 'delete':
                counts.delete++
                break
            case 'move':
                counts.move++
                break
            case 'search':
                counts.search++
                break
            case 'fetch':
                counts.fetch++
                break
            default:
                counts.other++
                break
        }
        addIcon(`kind:${kind ?? 'other'}`)
    }

    const active = lastToolStatus === 'pending' || lastToolStatus === 'in_progress'
    const hasCountableWork =
        counts.execute +
            counts.read +
            counts.edit +
            counts.delete +
            counts.move +
            counts.search +
            counts.fetch +
            counts.subagents +
            counts.other >
        0
    return { counts, icons, liveLabel, active, hasCountableWork, doneLabel: buildDoneLabel(counts) }
}

// Completed turns are stable by reference, so their summary never changes — cache it keyed on the
// group's (stable) first item to avoid re-walking frozen groups on every streamed token. The active
// (incomplete) turn is never cached, so its live label stays correct.
const summaryCache = new WeakMap<ThreadItem, { len: number; summary: GroupSummary }>()

function summarizeMemo(
    leading: ThreadItem[],
    invocations: Map<string, ToolInvocation>,
    turnComplete: boolean
): GroupSummary {
    const key = leading[0]
    if (turnComplete) {
        const cached = summaryCache.get(key)
        if (cached && cached.len === leading.length) {
            return cached.summary
        }
    }
    const summary = summarize(leading, invocations)
    if (turnComplete) {
        summaryCache.set(key, { len: leading.length, summary })
    }
    return summary
}

/**
 * Fold the flat thread items into rows, collapsing each completed turn's tool-call work into a
 * chip according to the collapse mode and any per-group overrides.
 *
 * Per-group turn completeness is derived from the projection's `turn_separator` items: a group whose
 * items sit at/before the last separator belongs to a finished turn; the trailing group (the live
 * turn) uses `currentTurnComplete`.
 */
export function buildThreadGroups(
    items: ThreadItem[],
    invocations: Map<string, ToolInvocation>,
    mode: CollapseMode,
    overrides: Record<string, boolean>,
    currentTurnComplete: boolean
): ThreadRow[] {
    const lastSeparatorIndex = items.findLastIndex((item) => item.type === 'turn_separator')
    const rows: ThreadRow[] = []
    let buffer: { item: ThreadItem; index: number }[] = []

    const pushItemRow = (item: ThreadItem): void => {
        rows.push({ kind: 'item', id: item.id, item })
    }

    const flush = (): void => {
        if (buffer.length === 0) {
            return
        }
        const leading = buffer.map((b) => b.item)
        const first = buffer[0]
        // A group in a finished turn (its first item precedes the last turn separator) is always
        // complete; only the live, trailing turn defers to the stream's current turn state.
        const turnComplete = first.index <= lastSeparatorIndex || currentTurnComplete
        const groupId = `group:${first.item.id}`

        // Base behavior from the mode; a per-group override (true=expanded, false=collapsed) wins.
        // A chip shows whenever the group is collapsible by the mode or the user explicitly collapsed it.
        const baseCollapse = mode === 'all' || (mode === 'partial' && turnComplete)
        const override = overrides[groupId]
        const expanded = override ?? !baseCollapse
        const chipPresent = baseCollapse || override === false

        if (chipPresent) {
            rows.push({
                kind: 'tool_group',
                id: groupId,
                items: leading,
                summary: summarizeMemo(leading, invocations, turnComplete),
                turnComplete,
                expanded,
            })
        } else {
            for (const item of leading) {
                pushItemRow(item)
            }
        }
        buffer = []
    }

    items.forEach((item, index) => {
        if (isGroupableItem(item)) {
            buffer.push({ item, index })
        } else {
            flush()
            pushItemRow(item)
        }
    })
    flush()

    return rows
}
