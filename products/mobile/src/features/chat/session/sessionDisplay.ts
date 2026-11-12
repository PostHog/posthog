import type { TaskRunStatus } from '@/model/types'

import type {
    SessionActivityGroup,
    SessionDisplayItem,
    SessionErrorItem,
    SessionProgressStep,
    SessionThreadItem,
    SessionToolInvocation,
} from './types'

export function groupSessionItems(items: SessionThreadItem[]): SessionDisplayItem[] {
    const result: SessionDisplayItem[] = []
    let group: SessionActivityGroup | undefined
    for (const item of items) {
        if (item.kind !== 'thought' && item.kind !== 'tool') {
            group = undefined
            result.push(item)
            continue
        }
        if (!group) {
            group = { kind: 'activity', id: `activity-${item.id}`, items: [] }
            result.push(group)
        }
        group.items.push(item)
    }
    return result
}

function isToolRunning(invocation: SessionToolInvocation | undefined): boolean {
    return invocation?.status === 'pending' || invocation?.status === 'in_progress'
}

/** `waitingToolCallId` is the call the agent paused on for a decision; it waits on the person, so it does not run. */
export function isActivityRunning(
    group: SessionActivityGroup,
    invocations: ReadonlyMap<string, SessionToolInvocation>,
    waitingToolCallId?: string
): boolean {
    return group.items.some((item) =>
        item.kind === 'thought'
            ? !item.complete
            : item.toolCallId !== waitingToolCallId && isToolRunning(invocations.get(item.toolCallId))
    )
}

const SUBAGENT_TOOLS = new Set(['Task', 'Agent'])

type CountedKind = 'execute' | 'read' | 'list' | 'edit' | 'delete' | 'move' | 'search' | 'fetch'

const COUNTED_KINDS = new Set<string>(['execute', 'read', 'list', 'edit', 'delete', 'move', 'search', 'fetch'])

function plural(count: number, singular: string, pluralForm: string): string {
    return `${count} ${count === 1 ? singular : pluralForm}`
}

function files(count: number): string {
    return count === 1 ? 'a file' : `${count} files`
}

/** The web thread's wording for a settled run, such as "Ran 5 commands, read 2 files". */
function summarizeTools(calls: (SessionToolInvocation | undefined)[]): string {
    const counts: Record<CountedKind | 'subagents' | 'other', number> = {
        execute: 0,
        read: 0,
        list: 0,
        edit: 0,
        delete: 0,
        move: 0,
        search: 0,
        fetch: 0,
        subagents: 0,
        other: 0,
    }
    for (const call of calls) {
        if (call && SUBAGENT_TOOLS.has(call.toolName)) {
            counts.subagents += 1
        } else if (call?.kind && COUNTED_KINDS.has(call.kind)) {
            counts[call.kind as CountedKind] += 1
        } else {
            counts.other += 1
        }
    }
    const parts = [
        counts.execute > 0 && `ran ${plural(counts.execute, 'command', 'commands')}`,
        counts.read > 0 && `read ${files(counts.read)}`,
        counts.list > 0 && `listed ${plural(counts.list, 'directory', 'directories')}`,
        counts.edit > 0 && `edited ${files(counts.edit)}`,
        counts.delete > 0 && `deleted ${files(counts.delete)}`,
        counts.move > 0 && `moved ${files(counts.move)}`,
        counts.search > 0 && `ran ${plural(counts.search, 'search', 'searches')}`,
        counts.fetch > 0 && `fetched ${plural(counts.fetch, 'page', 'pages')}`,
        counts.subagents > 0 && `ran ${plural(counts.subagents, 'subagent', 'subagents')}`,
        counts.other > 0 && plural(counts.other, 'tool call', 'tool calls'),
    ].filter((part): part is string => !!part)
    if (parts.length === 0) {
        return 'Worked'
    }
    const label = parts.join(', ')
    return label.charAt(0).toUpperCase() + label.slice(1)
}

/** A running group names its current step; a settled one counts what it did. */
export function summarizeActivity(
    group: SessionActivityGroup,
    invocations: ReadonlyMap<string, SessionToolInvocation>,
    waitingToolCallId?: string
): string {
    const calls = group.items.flatMap((item) =>
        item.kind === 'tool' && item.toolCallId !== waitingToolCallId ? [invocations.get(item.toolCallId)] : []
    )
    if (isActivityRunning(group, invocations, waitingToolCallId)) {
        const current = calls.filter(isToolRunning).at(-1)
        return current ? (current.title ?? current.toolName) : 'Thinking…'
    }
    if (calls.length === 0) {
        return 'Thought for a moment'
    }
    return summarizeTools(calls)
}

export function errorItemText(item: SessionErrorItem): string {
    switch (item.variant) {
        case 'crash':
            return `The agent stopped unexpectedly.\n${item.message}`
        case 'undelivered':
            return `Your message didn't reach the agent.\n${item.message}`
        case 'error':
            return item.message
    }
}

/** A failed run often logs its failure as an error item too, so the thread shows it only once. */
export function shouldShowRunError(
    items: SessionThreadItem[],
    runStatus: TaskRunStatus | null,
    runError: string | undefined
): runError is string {
    if (runStatus !== 'failed' || !runError) {
        return false
    }
    return !items.some((item) => item.kind === 'error' && item.message.includes(runError))
}

export function progressHeadline(steps: SessionProgressStep[]): string | undefined {
    return (steps.find((step) => step.status === 'in_progress') ?? steps.at(-1))?.label
}
