import type { ToolInvocation, ToolInvocationStatus } from '../types/streamTypes'
import { diffToolStream, type MatchedInvocation } from './useToolStream'

function inv(toolCallId: string, status: ToolInvocationStatus): ToolInvocation {
    return {
        toolCallId,
        rawServerName: 'posthog',
        rawToolName: 'exec',
        input: {},
        status,
        contentBlocks: [],
    }
}

const matched = (invocation: ToolInvocation): MatchedInvocation => ({ invocation, resolvedKey: 'create_insight' })
const kinds = (prev: Map<string, ToolInvocationStatus>, i: ToolInvocation): string[] =>
    diffToolStream(prev, [matched(i)]).map((e) => e.kind)

describe('diffToolStream', () => {
    it.each<[string, ToolInvocationStatus | undefined, ToolInvocationStatus, string[]]>([
        ['newly seen pending → started', undefined, 'pending', ['started']],
        ['newly seen in_progress → started', undefined, 'in_progress', ['started']],
        ['fast tool seen already completed → started + completed', undefined, 'completed', ['started', 'completed']],
        ['fast tool seen already failed → started + failed', undefined, 'failed', ['started', 'failed']],
        ['pending → in_progress → updated', 'pending', 'in_progress', ['updated']],
        ['in_progress → completed → completed', 'in_progress', 'completed', ['completed']],
        ['in_progress → failed → failed', 'in_progress', 'failed', ['failed']],
    ])('%s', (_label, prevStatus, nextStatus, expected) => {
        const prev = new Map<string, ToolInvocationStatus>()
        if (prevStatus) {
            prev.set('t1', prevStatus)
        }
        expect(kinds(prev, inv('t1', nextStatus))).toEqual(expected)
    })

    it('fires nothing when a tool is re-observed at an unchanged status (the seed guard’s guarantee)', () => {
        // A seeded baseline holds the terminal status; opening/replaying a finished run must not re-fire.
        const prev = new Map<string, ToolInvocationStatus>([['t1', 'completed']])
        expect(kinds(prev, inv('t1', 'completed'))).toEqual([])
    })

    it('fires a terminal event only once across successive diffs', () => {
        const prev = new Map<string, ToolInvocationStatus>([['t1', 'in_progress']])
        expect(kinds(prev, inv('t1', 'completed'))).toEqual(['completed'])
        // Same completed invocation observed again — no second completion.
        expect(kinds(prev, inv('t1', 'completed'))).toEqual([])
    })

    it('emits per-tool events for a mixed batch', () => {
        const prev = new Map<string, ToolInvocationStatus>([['known', 'in_progress']])
        const events = diffToolStream(prev, [matched(inv('fresh', 'pending')), matched(inv('known', 'completed'))])
        expect(events.map((e) => [e.event.invocation.toolCallId, e.kind])).toEqual([
            ['fresh', 'started'],
            ['known', 'completed'],
        ])
    })
})
