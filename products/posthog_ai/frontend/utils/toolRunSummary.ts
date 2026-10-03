import type { ToolInvocation } from '../types/streamTypes'
import { resolveToolCall } from './toolResolver'

const SUBAGENT_TOOLS = new Set(['Task', 'Agent'])

type CountedKind = 'execute' | 'read' | 'list' | 'edit' | 'delete' | 'move' | 'search' | 'fetch'

const COUNTED_KINDS = new Set<string>(['execute', 'read', 'list', 'edit', 'delete', 'move', 'search', 'fetch'])

function plural(count: number, singular: string, pluralForm: string): string {
    return `${count} ${count === 1 ? singular : pluralForm}`
}

function files(count: number): string {
    return count === 1 ? 'a file' : `${count} files`
}

/** PostHog Desktop's wording for a settled run, such as "Ran 5 commands, read 2 files". */
export function summarizeToolRun(calls: ToolInvocation[]): string {
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
        const { claudeToolName, resolvedKey } = resolveToolCall(call)
        if (SUBAGENT_TOOLS.has(claudeToolName ?? resolvedKey)) {
            counts.subagents += 1
        } else if (call.kind && COUNTED_KINDS.has(call.kind)) {
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
