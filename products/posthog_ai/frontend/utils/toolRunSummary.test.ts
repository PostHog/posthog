import type { ToolInvocation } from '../types/streamTypes'
import { summarizeToolRun } from './toolRunSummary'

describe('summarizeToolRun', () => {
    const call = (kind: string | undefined, toolName?: string): ToolInvocation => ({
        toolCallId: `${kind}-${toolName}`,
        rawServerName: 'posthog',
        rawToolName: toolName ?? 'exec',
        input: {},
        status: 'completed',
        kind,
        contentBlocks: [],
        meta: toolName ? { claudeCode: { toolName } } : undefined,
    })

    it.each<[string, ToolInvocation[], string]>([
        [
            'counts each kind in desktop order',
            [call('read', 'Read'), call('execute', 'Bash'), call('execute', 'Bash'), call('other'), call('other')],
            'Ran 2 commands, read a file, 2 tool calls',
        ],
        [
            'reads one of each in the singular',
            [call('search', 'Grep'), call('edit', 'Edit')],
            'Edited a file, ran 1 search',
        ],
        ['counts a subagent by its tool, not its kind', [call('think', 'Task')], 'Ran 1 subagent'],
    ])('%s', (_, calls, label) => {
        expect(summarizeToolRun(calls)).toBe(label)
    })
})
