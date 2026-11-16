import { classicToolInvocations } from './classicActivity'
import {
    appendClassicMessage,
    classicHistory,
    classicThreadItems,
    EMPTY_CLASSIC_STATE,
    reduceClassicEvent,
} from './classicMessages'

describe('classic conversation events', () => {
    test.each(['form', 'approval'] as const)(
        'keeps a tool awaiting a %s response pending until its result arrives',
        (decision) => {
            let state = classicHistory(
                [
                    { id: 'question', type: 'human', content: 'Configure an event report.' },
                    {
                        id: 'request',
                        type: 'ai',
                        content: '',
                        tool_calls: [
                            {
                                id: 'waiting-tool',
                                name: decision === 'form' ? 'create_form' : 'create_insight',
                                args:
                                    decision === 'form'
                                        ? {
                                              questions: [
                                                  {
                                                      id: 'event',
                                                      question: 'Which event?',
                                                      options: [{ value: 'signup' }],
                                                  },
                                              ],
                                          }
                                        : {},
                            },
                        ],
                    },
                ],
                null,
                decision === 'approval'
                    ? [
                          {
                              proposal_id: 'proposal',
                              decision_status: 'pending',
                              original_tool_call_id: 'waiting-tool',
                          },
                      ]
                    : []
            )
            expect(classicToolInvocations(state, false).get('waiting-tool')?.status).toBe('pending')
            state = appendClassicMessage(state, {
                type: 'tool',
                tool_call_id: 'waiting-tool',
                content: 'Response received.',
            })
            expect(classicToolInvocations(state, false).get('waiting-tool')?.status).toBe('completed')
        }
    )
    test.each(['history', 'stream'])(
        'folds structured intermediate responses and keeps the final answer in %s',
        (source) => {
            const messages = [
                { id: 'question', type: 'human', content: 'Compare signups.', trace_id: 'trace-signups' },
                { id: 'commentary', type: 'ai', content: 'I will inspect the signup events.' },
                {
                    id: 'inspection',
                    type: 'ai',
                    content: 'Checking the selected dates.',
                    meta: { thinking: [{ type: 'thinking', thinking: 'Use matching date ranges.' }] },
                    tool_calls: [
                        { id: 'query-signups', name: 'query_insight', args: { context: 'Compare signup events' } },
                    ],
                },
                { type: 'tool', tool_call_id: 'query-signups', content: 'Query completed.' },
                { id: 'summary', type: 'ai', content: '**Signups increased.**' },
            ]
            const state =
                source === 'history'
                    ? classicHistory(messages, null)
                    : messages.reduce(appendClassicMessage, EMPTY_CLASSIC_STATE)
            const items = classicThreadItems(state, '')
            expect(items.map((item) => item.kind)).toEqual([
                'user',
                'thought',
                'thought',
                'thought',
                'tool',
                'assistant',
            ])
            expect(items.at(-1)).toMatchObject({
                text: '**Signups increased.**',
                traceId: 'trace-signups',
                complete: true,
            })
            expect(classicToolInvocations(state, false).get('query-signups')).toMatchObject({
                status: 'completed',
                detail: 'Compare signup events',
            })
        }
    )

    test('keeps tool results separate without wire message IDs and preserves their latest progress', () => {
        let state = classicHistory(
            [
                { id: 'question', type: 'human', content: 'Compare two events.' },
                {
                    id: 'inspection',
                    type: 'ai',
                    content: '',
                    tool_calls: [
                        { id: 'first', name: 'query_insight', args: {} },
                        { id: 'second', name: 'query_insight', args: {} },
                    ],
                },
            ],
            null
        )
        expect([...classicToolInvocations(state, true).values()].map((tool) => tool.status)).toEqual([
            'in_progress',
            'in_progress',
        ])
        state = reduceClassicEvent(state, {
            event: 'update',
            data: JSON.stringify({ tool_call_id: 'second', content: 'Running the second query.' }),
        })
        state = appendClassicMessage(state, { type: 'tool', tool_call_id: 'first', content: 'First result' })
        state = appendClassicMessage(state, {
            type: 'tool',
            tool_call_id: 'second',
            content: 'Query unavailable.',
            status: 'error',
        })
        expect([...classicToolInvocations(state, false).values()]).toMatchObject([
            { status: 'completed' },
            { status: 'failed', detail: 'Running the second query.', errorMessage: 'Query unavailable.' },
        ])
        expect(state.messages.filter((message) => message.data.type === 'tool')).toHaveLength(2)
    })

    test('reads all reasoning summaries and settles temporary thinking after an interrupted stream', () => {
        const state = appendClassicMessage(EMPTY_CLASSIC_STATE, {
            id: 'temp-thinking',
            type: 'ai',
            content: '',
            meta: {
                thinking: [
                    { type: 'reasoning', summary: [{ text: 'Inspect the events.' }, { text: 'Compare the counts.' }] },
                    { type: 'reasoning', summary: null },
                    null,
                ],
            },
        })
        expect(classicThreadItems(state, '', true)).toEqual([
            {
                kind: 'thought',
                id: 'stream-0-thinking-0',
                text: 'Inspect the events.\n\nCompare the counts.',
                complete: false,
            },
        ])
        expect(classicThreadItems(state, '', false)[0]).toMatchObject({ complete: true })
        const failed = appendClassicMessage(state, {
            id: 'failure',
            type: 'ai/failure',
            content: 'The query failed. Try again.',
        })
        expect(classicThreadItems(failed, '').at(-1)).toMatchObject({
            kind: 'error',
            message: 'The query failed. Try again.',
        })
    })

    test('replaces the optimistic human echo and accumulated answer snapshots without duplicating turns', () => {
        let state = appendClassicMessage(EMPTY_CLASSIC_STATE, {
            type: 'human',
            content: 'A question',
            trace_id: 'trace-1',
        })
        state = appendClassicMessage(state, {
            id: 'human-1',
            type: 'human',
            content: 'A question',
            trace_id: 'trace-1',
        })
        state = appendClassicMessage(state, { type: 'ai', content: 'The' })
        state = appendClassicMessage(state, { type: 'ai', content: 'The answer' })
        state = appendClassicMessage(state, { id: 'ai-1', type: 'ai', content: 'The answer.' })
        state = appendClassicMessage(state, { id: 'ai-1', type: 'ai', content: 'The answer.' })
        expect(state.messages).toHaveLength(2)
        expect(classicThreadItems(state, '')).toEqual([
            { kind: 'user', id: 'stream-0', text: 'A question' },
            {
                kind: 'assistant',
                id: 'stream-1',
                text: 'The answer.',
                complete: true,
                projectUrl: '',
                traceId: 'trace-1',
            },
        ])
    })

    test('keeps separate answers and turns intact when loading history', () => {
        const state = classicHistory(
            [
                { id: 'a', type: 'ai', content: 'First answer' },
                { id: 'b', type: 'human', content: 'Follow-up' },
                { id: 'c', type: 'ai', content: 'Second answer', trace_id: 'trace-c' },
                { id: 'd', type: 'human', content: 'Another question' },
                { id: 'e', type: 'ai', content: 'Answer without a trace' },
            ],
            'Saved title'
        )
        expect(state.title).toBe('Saved title')
        expect(classicThreadItems(state, '').map((item) => item.id)).toEqual(['a', 'b', 'c', 'd', 'e'])
        expect(classicThreadItems(state, '')[2]).toMatchObject({ traceId: 'trace-c' })
        expect(classicThreadItems(state, '')[4]).not.toHaveProperty('traceId')
    })

    test('restores pending approvals and ignores malformed stream frames', () => {
        const approval = {
            proposal_id: 'proposal-1',
            decision_status: 'pending',
            tool_name: 'Create dashboard',
            preview: 'Create a dashboard',
        }
        const state = reduceClassicEvent(EMPTY_CLASSIC_STATE, {
            event: 'approval',
            data: JSON.stringify(approval),
        })
        expect(state.approval).toEqual({
            id: 'proposal-1',
            toolName: 'Create dashboard',
            preview: 'Create a dashboard',
        })
        expect(classicHistory([], null, [approval]).approval).toEqual(state.approval)
        expect(reduceClassicEvent(state, { event: 'message', data: '{broken' })).toBe(state)
        expect(reduceClassicEvent(state, { event: 'message', data: 'null' })).toBe(state)
    })

    test('preserves links to generated charts and saved insights', () => {
        const state = classicHistory(
            [
                { type: 'ai/viz', id: 'chart', answer: { kind: 'TrendsQuery', series: [] } },
                { type: 'ai/artifact', id: 'saved', source: 'insight', artifact_id: 'abc123', content: {} },
            ],
            null
        )
        const items = classicThreadItems(state, 'https://app.example.com/project/42')
        expect(items[0]).toMatchObject({ text: expect.stringContaining('/insights/new#q=') })
        expect(items[1]).toMatchObject({
            text: '[View insight](https://app.example.com/project/42/insights/abc123)',
        })
    })
    test('preserves distinct temporary answers while replacing snapshots of each', () => {
        let state = EMPTY_CLASSIC_STATE
        for (const data of [
            { id: 'temp-0', type: 'ai', content: 'Searching' },
            { id: 'temp-1', type: 'ai', content: 'Found' },
            { id: 'temp-0', type: 'ai', content: 'Searching the web' },
            { id: 'temp-1', type: 'ai', content: 'Found an answer' },
        ])
            state = appendClassicMessage(state, data)
        expect(classicThreadItems(state, '').map((item) => ('text' in item ? item.text : null))).toEqual([
            'Searching the web',
            'Found an answer',
        ])
    })

    test.each([
        [
            { kind: 'TrendsQuery', series: [] },
            { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] }, showHeader: true },
        ],
        [
            { kind: 'HogQLQuery', query: 'SELECT 1' },
            { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'SELECT 1' } },
        ],
        [
            {
                kind: 'DataVisualizationNode',
                source: { kind: 'HogQLQuery', query: 'SELECT 1' },
                display: 'ActionsBar',
            },
            {
                kind: 'DataVisualizationNode',
                source: { kind: 'HogQLQuery', query: 'SELECT 1' },
                display: 'ActionsBar',
            },
        ],
    ])('keeps chart links compatible with the query schema: %j', (query, expected) => {
        const state = classicHistory([{ type: 'ai/viz', id: 'chart', answer: query }], null)
        const item = classicThreadItems(state, 'https://app.example.com/project/42')[0]
        const encoded = item && 'text' in item ? (item.text.split('#q=')[1]?.slice(0, -1) ?? '') : ''
        expect(JSON.parse(decodeURIComponent(encoded))).toEqual(expected)
    })
    test.each(['Saved answer', 'Saved'])('reconciles replayed %s with unique IDs across model calls', (snapshot) => {
        let state = classicHistory(
            [
                { id: 'earlier', type: 'ai', content: 'Earlier turn' },
                { id: 'saved', type: 'ai', content: 'Saved answer' },
            ],
            null
        )
        state = appendClassicMessage(state, { id: 'temp-0', type: 'ai', content: snapshot })
        state = appendClassicMessage(state, { id: 'temp-1', type: 'ai', content: 'Next answer' })
        const nextId = state.messages.at(-1)?.id
        state = appendClassicMessage(state, { id: 'saved', type: 'ai', content: 'Saved answer' })
        expect(state.messages.map((message) => message.data.content)).toEqual([
            'Earlier turn',
            'Saved answer',
            'Next answer',
        ])
        state = appendClassicMessage(state, { id: 'next', type: 'ai', content: 'Next answer' })
        expect(state.messages.at(-1)?.id).toBe(nextId)
        state = appendClassicMessage(state, { id: 'temp-0', type: 'ai', content: 'Another call' })
        state = appendClassicMessage(state, { id: 'final', type: 'ai', content: 'Another call' })
        state = appendClassicMessage(state, { id: 'temp-0', type: 'ai', content: 'Last call' })
        const items = classicThreadItems(state, '')
        expect(new Set(items.map((item) => item.id)).size).toBe(items.length)
        expect(state.messages.map((message) => message.data.content)).toEqual([
            'Earlier turn',
            'Saved answer',
            'Next answer',
            'Another call',
            'Last call',
        ])
    })

    test.each(['stream', 'history'])('preserves notebook blocks from %s', (source) => {
        const data = {
            id: 'notebook-message',
            type: 'ai/artifact',
            source: 'artifact',
            artifact_id: 'report-1',
            content: {
                content_type: 'notebook',
                is_saved: true,
                blocks: [
                    { type: 'markdown', content: '# Report\n\nA synthetic summary.' },
                    { type: 'session_replay', session_id: 'session-1', timestamp_ms: 0 },
                    { type: 'markdown', content: 'A conclusion.' },
                ],
            },
        }
        const state =
            source === 'history'
                ? classicHistory([data], null)
                : reduceClassicEvent(EMPTY_CLASSIC_STATE, { event: 'message', data: JSON.stringify(data) })
        expect(classicThreadItems(state, 'https://app.example.com/project/42')[0]).toMatchObject({
            text: '# Report\n\nA synthetic summary.\n\nOpen this report on the web to view this content.\n\nA conclusion.\n\n[View notebook](https://app.example.com/project/42/notebooks/report-1)',
        })
        data.content.is_saved = false
        const draft = classicThreadItems(classicHistory([data], null), 'https://app.example.com/project/42')[0]
        expect(draft && 'text' in draft ? draft.text : '').not.toContain('[View notebook]')
    })
})
