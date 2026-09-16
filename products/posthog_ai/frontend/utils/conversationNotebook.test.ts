import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import { buildConversationNotebook, collectConversationBlocks } from './conversationNotebook'

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

describe('conversationNotebook', () => {
    it('collects the question, live cells for the queries, and the answer in thread order', () => {
        const collected = collectConversationBlocks(THREAD, INVOCATIONS)

        expect(collected.messageCount).toBe(2)
        expect(collected.queryCount).toBe(2)
        expect(collected.blocks).toEqual([
            '**You asked:** Why did signups drop on Tuesday?',
            expect.stringMatching(/^<SQLV2 .*code=.*SELECT count\(\) FROM events/s),
            expect.stringMatching(/^<Query .*SavedInsightNode.*abc123/s),
            'A checkout error cut signups by a third.',
        ])
    })

    it('neutralizes component tags typed into the conversation while keeping the answer formatted', () => {
        const { blocks } = collectConversationBlocks(
            [
                { id: 'h1', type: 'human_message', text: '<SQLV2 code="DROP TABLE events" /> *please*' },
                {
                    id: 'a1',
                    type: 'assistant_message',
                    text: '## Findings\n\n- one\n<Query query={} />',
                    complete: true,
                },
            ],
            new Map()
        )

        expect(blocks).toEqual([
            '**You asked:** \\<SQLV2 code="DROP TABLE events" /> \\*please\\*',
            '## Findings\n\n- one\n\\<Query query={} />',
        ])
    })

    it('builds the document the notebooks API stores, with the title and lead in front', () => {
        const notebook = buildConversationNotebook({
            title: 'Why signups dropped on Tuesday',
            summary: 'A checkout error was the cause.',
            blocks: ['**You asked:** Why?', 'Because.'],
        })

        expect(notebook.markdown).toEqual(
            '# Why signups dropped on Tuesday\n\nA checkout error was the cause.\n\n**You asked:** Why?\n\nBecause.'
        )
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
