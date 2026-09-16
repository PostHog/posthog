import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import { buildConversationNotebook } from './conversationNotebook'

jest.mock('lib/utils/dom', () => ({ ...jest.requireActual('lib/utils/dom'), uuid: () => 'node-1' }))

function execInvocation(toolCallId: string, command: string, output: unknown): ToolInvocation {
    return {
        toolCallId,
        rawServerName: 'posthog',
        rawToolName: 'exec',
        input: { command },
        output,
        status: 'completed',
        contentBlocks: [],
        meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
    }
}

const THREAD: ThreadItem[] = [
    { id: 'h1', type: 'human_message', text: 'Why did signups drop on Tuesday?' },
    { id: 't1', type: 'tool_invocation', toolCallId: 'sql' },
    { id: 't2', type: 'tool_invocation', toolCallId: 'insight' },
    { id: 't3', type: 'tool_invocation', toolCallId: 'recordings' },
    { id: 'a1', type: 'assistant_message', text: 'A checkout error cut signups by a third.', complete: true },
    { id: 'sep', type: 'turn_separator' },
]

const INVOCATIONS = new Map<string, ToolInvocation>([
    [
        'sql',
        execInvocation('sql', 'call execute-sql {"query":"SELECT count() FROM events"}', {
            query: { kind: 'HogQLQuery', query: 'SELECT count() FROM events' },
            results: [[1]],
        }),
    ],
    [
        'insight',
        execInvocation('insight', 'call insight-create {"name":"Signups"}', {
            short_id: 'abc123',
            name: 'Signups',
            query: { kind: 'TrendsQuery', series: [] },
        }),
    ],
    ['recordings', execInvocation('recordings', 'call query-session-recordings-list {}', { results: [] })],
])

describe('buildConversationNotebook', () => {
    it('writes the question, live cells for the queries, and the answer in thread order', () => {
        const notebook = buildConversationNotebook({
            title: 'Why signups dropped on Tuesday',
            summary: 'A checkout error was the cause.',
            threadItems: THREAD,
            toolInvocations: INVOCATIONS,
        })

        expect(notebook.messageCount).toBe(2)
        expect(notebook.queryCount).toBe(2)
        expect(notebook.markdown.split('\n\n')).toEqual([
            '# Why signups dropped on Tuesday',
            'A checkout error was the cause.',
            '**You asked:** Why did signups drop on Tuesday?',
            expect.stringMatching(/^<SQLV2 .*code=.*SELECT count\(\) FROM events/s),
            expect.stringMatching(/^<Query .*SavedInsightNode.*abc123/s),
            'A checkout error cut signups by a third.',
        ])
        expect(notebook.content).toEqual({
            type: 'doc',
            content: [
                {
                    type: 'ph-markdown-notebook',
                    attrs: { nodeId: 'markdown-notebook-v2', markdown: notebook.markdown },
                },
            ],
        })
    })
})
