import { groupSessionItems, isActivityRunning, shouldShowRunError, summarizeActivity } from './sessionDisplay'
import type { SessionActivityGroup, SessionThreadItem, SessionToolInvocation, SessionToolStatus } from './types'

function tool(
    toolCallId: string,
    kind: string | undefined,
    status: SessionToolStatus = 'completed',
    toolName = 'Bash',
    title?: string
): SessionToolInvocation {
    return { toolCallId, toolName, kind, status, title }
}

function groupOf(
    calls: SessionToolInvocation[],
    thoughts: { complete: boolean }[] = []
): {
    group: SessionActivityGroup
    invocations: Map<string, SessionToolInvocation>
} {
    return {
        group: {
            kind: 'activity',
            id: 'activity-x',
            items: [
                ...thoughts.map((thought, index) => ({
                    kind: 'thought' as const,
                    id: `t${index}`,
                    text: 'Hmm',
                    complete: thought.complete,
                })),
                ...calls.map((call) => ({
                    kind: 'tool' as const,
                    id: `i-${call.toolCallId}`,
                    toolCallId: call.toolCallId,
                })),
            ],
        },
        invocations: new Map(calls.map((call) => [call.toolCallId, call])),
    }
}

describe('sessionDisplay', () => {
    test('groupSessionItems folds consecutive thoughts and tools and breaks on any other item', () => {
        const items: SessionThreadItem[] = [
            { kind: 'user', id: 'u1', text: 'Fix it' },
            { kind: 'thought', id: 'th1', text: 'Look first', complete: true },
            { kind: 'tool', id: 'tl1', toolCallId: 'c1' },
            { kind: 'tool', id: 'tl2', toolCallId: 'c2' },
            { kind: 'assistant', id: 'a1', text: 'Found it', complete: true },
            { kind: 'tool', id: 'tl3', toolCallId: 'c3' },
            { kind: 'turn_end', id: 'e1' },
            { kind: 'thought', id: 'th2', text: 'Next', complete: false },
        ]
        const grouped = groupSessionItems(items)
        expect(grouped.map((item) => (item.kind === 'activity' ? item.items.map((row) => row.id) : item.id))).toEqual([
            'u1',
            ['th1', 'tl1', 'tl2'],
            'a1',
            ['tl3'],
            'e1',
            ['th2'],
        ])
        expect(grouped.filter((item) => item.kind === 'activity').map((item) => item.id)).toEqual([
            'activity-th1',
            'activity-tl3',
            'activity-th2',
        ])
    })

    test.each<[string, SessionToolInvocation[], string]>([
        ['one command', [tool('a', 'execute')], 'Ran 1 command'],
        [
            'commands and one file',
            [tool('a', 'execute'), tool('b', 'execute'), tool('c', 'read')],
            'Ran 2 commands, read a file',
        ],
        ['several files', [tool('a', 'read'), tool('b', 'read'), tool('c', 'edit')], 'Read 2 files, edited a file'],
        [
            'directories and searches',
            [tool('a', 'list'), tool('b', 'list'), tool('c', 'search')],
            'Listed 2 directories, ran 1 search',
        ],
        [
            'fetches, moves and deletes',
            [tool('a', 'fetch'), tool('b', 'move'), tool('c', 'delete')],
            'Deleted a file, moved a file, fetched 1 page',
        ],
        [
            'subagents by tool name',
            [tool('a', 'think', 'completed', 'Task'), tool('b', undefined, 'completed', 'Agent')],
            'Ran 2 subagents',
        ],
        ['unknown kinds', [tool('a', 'other'), tool('b', undefined)], '2 tool calls'],
        ['a failed tool still counts', [tool('a', 'execute', 'failed')], 'Ran 1 command'],
    ])('summarizes a settled group with %s', (_name, calls, expected) => {
        const { group, invocations } = groupOf(calls)
        expect(summarizeActivity(group, invocations)).toBe(expected)
    })

    test.each<[string, SessionToolInvocation[], { complete: boolean }[], string]>([
        ['only settled thoughts', [], [{ complete: true }], 'Thought for a moment'],
        ['a thought still streaming', [tool('a', 'execute')], [{ complete: false }], 'Thinking…'],
        [
            'a running tool with a title',
            [tool('a', 'read'), tool('b', 'execute', 'in_progress', 'Bash', 'pnpm test')],
            [],
            'pnpm test',
        ],
        ['a pending tool without a title', [tool('a', 'execute', 'pending', 'Grep')], [{ complete: false }], 'Grep'],
    ])('summarizes %s', (_name, calls, thoughts, expected) => {
        const { group, invocations } = groupOf(calls, thoughts)
        expect(summarizeActivity(group, invocations)).toBe(expected)
    })

    test('a tool call the agent paused on for a decision neither runs nor counts', () => {
        const { group, invocations } = groupOf([tool('a', 'read'), tool('ask', 'other', 'pending', 'AskUserQuestion')])
        expect(isActivityRunning(group, invocations, 'ask')).toBe(false)
        expect(summarizeActivity(group, invocations, 'ask')).toBe('Read a file')
        expect(summarizeActivity(group, invocations)).toBe('AskUserQuestion')
    })

    test.each<[string, SessionThreadItem[], 'failed' | 'completed', string | undefined, boolean]>([
        ['a failed run', [], 'failed', 'Sandbox timed out', true],
        [
            'a failure an error item already shows',
            [{ kind: 'error', id: 'e', message: 'Error: Sandbox timed out', variant: 'error' }],
            'failed',
            'Sandbox timed out',
            false,
        ],
        ['a finished run', [], 'completed', 'Sandbox timed out', false],
        ['a failed run with no message', [], 'failed', undefined, false],
    ])('shouldShowRunError for %s', (_name, items, status, runError, expected) => {
        expect(shouldShowRunError(items, status, runError)).toBe(expected)
    })
})
