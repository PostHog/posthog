import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'

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
    it('collects the question, the query cells and the answer in thread order, and serializes cells only on build', () => {
        const collected = collectConversationBlocks(THREAD, INVOCATIONS)

        expect(collected.messageCount).toBe(2)
        expect(collected.queryCount).toBe(2)
        expect(collected.blocks).toEqual([
            '**You asked:** Why did signups drop on Tuesday?',
            { component: 'SQLV2', props: expect.objectContaining({ code: 'SELECT count() FROM events' }) },
            { component: 'Query', props: { query: { kind: 'SavedInsightNode', shortId: 'abc123' } } },
            'A checkout error cut signups by a third.',
        ])

        const { markdown } = buildConversationNotebook({ title: 'Why', summary: '', blocks: collected.blocks })
        expect(markdown.split('\n\n').slice(1)).toEqual([
            '**You asked:** Why did signups drop on Tuesday?',
            expect.stringMatching(/^<SQLV2 .*nodeId="node-1".*code=.*SELECT count\(\) FROM events/s),
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
                    text: '## Findings\n\n- one\n<Query query={} />\n> > <Embed src="https://example.com" />\n```tsx\n<Button />\n```',
                    complete: true,
                },
                {
                    id: 'a2',
                    type: 'assistant_message',
                    text: '```\n<Embed src="https://example.com" />',
                    complete: true,
                },
                {
                    id: 'a3',
                    type: 'assistant_message',
                    text: '````markdown\n```python\n<PythonV2 code="print(1)" />\n```\n````',
                    complete: true,
                },
            ],
            new Map()
        )

        expect(blocks).toEqual([
            '**You asked:** \\<SQLV2 code="DROP TABLE events" /> \\*please\\*',
            '## Findings\n\n- one\n`<Query` query={} />\n> > `<Embed` src="https://example.com" />\n```tsx\n`<Button` />\n```',
            '```\n`<Embed` src="https://example.com" />',
            '````markdown\n```python\n`<PythonV2` code="print(1)" />\n```\n````',
        ])
    })

    const answer = (id: string, text: string): ThreadItem => ({ id, type: 'assistant_message', text, complete: true })
    const cell = 'PythonV2 nodeId="x" code="print(1)"'

    it.each<[string, ThreadItem[], string]>([
        ['a bare opener spread over lines', [answer('a1', `See below.\n\n<${cell}\n  title="Report" />`)], 'Report'],
        ['a backslash opener spread over lines', [answer('a1', `See below.\n\n\\<${cell}\n  title="R" />`)], 'R'],
        ['a carriage return before the tag', [answer('a1', `Report\r<${cell} />`)], 'Report'],
        ['a control character the backend strips', [answer('a1', `\x1c<${cell} />`)], 'Report'],
        [
            'a tag in the question',
            [{ id: 'h1', type: 'human_message', text: `Question\n\n<${cell}\n/>` }, answer('a1', 'Done.')],
            'Report',
        ],
        ['a line break in the title', [answer('a1', 'Done.')], `Report\n<${cell} />`],
        [
            'a fence one answer leaves open for the backend only',
            [answer('a1', '`````\n```\n`````'), answer('a2', `\`\`\`tsx\n<${cell} />\n\`\`\``)],
            'Report',
        ],
    ])('keeps %s from becoming a live cell in the editor or the notebooks backend', (_label, thread, title) => {
        const { blocks } = collectConversationBlocks(thread, new Map())
        const { markdown } = buildConversationNotebook({ title, summary: '', blocks })

        expect(parseMarkdownNotebook(markdown).nodes.some((node) => node.type === 'component')).toBe(false)
        // The backend's run-all parser takes any line that starts with a tag once Python's `strip()` runs.
        const backendLines = markdown.replace(/\r\n?/g, '\n').split('\n')
        expect(backendLines.filter((line) => /^[\s\x1c-\x1f\x85]*\\?<[A-Z]/.test(line))).toEqual([])
    })

    it('lays an incident write-up out as timeline, cause, evidence and fix around the conversation', () => {
        const { markdown } = buildConversationNotebook({
            title: 'Why signups dropped on Tuesday',
            summary: 'A checkout error was the cause.',
            blocks: ['**You asked:** Why?', 'Because.'],
            incident: { timeline: '- 14:10 release\n- 14:25 first error', cause: 'Checkout error.', fix: '' },
        })

        expect(markdown.split('\n\n')).toEqual([
            '# Why signups dropped on Tuesday',
            'A checkout error was the cause.',
            '## Timeline',
            '- 14:10 release\n- 14:25 first error',
            '## Cause',
            'Checkout error.',
            '## Evidence',
            '**You asked:** Why?',
            'Because.',
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
