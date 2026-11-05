import {
    appendClassicMessage,
    classicHistory,
    classicThreadItems,
    EMPTY_CLASSIC_STATE,
    reduceClassicEvent,
} from './classicMessages'

describe('classic conversation events', () => {
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
            { kind: 'assistant', id: 'stream-1', text: 'The answer.', complete: true },
        ])
    })

    test('keeps separate answers and turns intact when loading history', () => {
        const state = classicHistory(
            [
                { id: 'a', type: 'ai', content: 'First answer' },
                { id: 'b', type: 'human', content: 'Follow-up' },
                { id: 'c', type: 'ai', content: 'Second answer' },
            ],
            'Saved title'
        )
        expect(state.title).toBe('Saved title')
        expect(classicThreadItems(state, '').map((item) => item.id)).toEqual(['a', 'b', 'c'])
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
})
