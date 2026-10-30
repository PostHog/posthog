import type { IssueEventApi, IssueListItemApi } from '@/api/errorTracking'

import {
    breakdownRows,
    emptyCopy,
    highlightStart,
    type IssueRowContext,
    issueFrames,
    issueRowFrom,
    sampleSessions,
    trendCaption,
} from './issueModel'

const NOW = new Date('2026-10-20T12:00:00Z')

function context(overrides: Partial<IssueRowContext> = {}): IssueRowContext {
    return { window: '24h', now: NOW, spiking: new Set(), myUserId: 7, ...overrides }
}

function issue(overrides: Partial<IssueListItemApi> = {}): IssueListItemApi {
    return {
        id: '11111111-1111-4111-8111-111111111111',
        name: 'TypeError',
        description: "Cannot read properties of undefined (reading 'id')",
        status: 'active',
        first_seen: '2026-10-01T00:00:00Z',
        assignee: null,
        aggregations: { users: 42.0, occurrences: 118, sessions: 61, volumeRange: [0, 1, 2] },
        ...overrides,
    }
}

describe('issueRowFrom', () => {
    test.each([
        ['first seen inside the window is new', { first_seen: '2026-10-20T08:00:00Z' }, false, 'new'],
        ['new wins over a spike', { first_seen: '2026-10-20T08:00:00Z' }, true, 'new'],
        ['a detected spike on an older issue is spiking', {}, true, 'spiking'],
        ['an older issue without a spike has no badge', {}, false, null],
        ['first seen just before the window is not new', { first_seen: '2026-10-19T11:59:00Z' }, false, null],
    ])('%s', (_name, overrides, spiking, badge) => {
        const api = issue(overrides)
        const row = issueRowFrom(api, context({ spiking: new Set(spiking ? [api.id] : []) }))
        expect(row.badge).toBe(badge)
    })

    test.each([
        [null, { kind: 'none' }],
        [{ type: 'user', id: 7 }, { kind: 'me' }],
        [
            { type: 'user', id: 8 },
            { kind: 'user', id: 8 },
        ],
        [
            { type: 'role', id: 'b5e1c2a4-0000-4000-8000-000000000000' },
            { kind: 'role', id: 'b5e1c2a4-0000-4000-8000-000000000000' },
        ],
    ])('reads the assignee %j as %j', (assignee, expected) => {
        expect(issueRowFrom(issue({ assignee }), context()).assignee).toEqual(expected)
    })
})

test.each(['new', 'spiking'] as const)(
    '%s does not claim the entire window is empty before pagination ends',
    (filter) => {
        const progress = { hasMore: true, spikesLoading: false, spikesFailed: false }
        expect(emptyCopy(filter, '24h', progress).title).toBe('No matches in loaded issues')
        expect(emptyCopy(filter, '24h', { ...progress, hasMore: false }).title).not.toBe('No matches in loaded issues')
    }
)

test('Spiking distinguishes pending and failed badge lookups from an empty result', () => {
    expect(emptyCopy('spiking', '24h', { hasMore: false, spikesLoading: true, spikesFailed: false })).toMatchObject({
        title: 'Checking for spikes…',
        action: null,
    })
    expect(emptyCopy('spiking', '24h', { hasMore: false, spikesLoading: false, spikesFailed: true })).toMatchObject({
        title: "Couldn't check for spikes",
        action: { kind: 'retry_spikes' },
    })
})

describe('highlightStart', () => {
    test.each([
        ['no badge draws gray', [1, 2, 3], null, null],
        ['a new issue lights up from its first occurrence', [0, 0, 3, 5], 'new', 2],
        ['a spike lights up the trailing run above the median', [4, 5, 4, 5, 4, 12, 20], 'spiking', 5],
        ['a spike with a flat tail still marks the last bucket', [5, 5, 5, 5], 'spiking', 3],
    ] as const)('%s', (_name, values, badge, expected) => {
        expect(highlightStart(values, badge)).toBe(expected)
    })
})

describe('issueFrames', () => {
    const event = (frames: object[] | null, overrides: Partial<IssueEventApi> = {}): IssueEventApi => ({
        timestamp: '2026-10-20T11:00:00Z',
        properties: {
            $exception_list: [{ type: 'TypeError', stacktrace: frames ? { frames } : null }],
        },
        ...overrides,
    })

    test('lists in-app frames innermost first, with resolved names and file:line', () => {
        const result = issueFrames(
            [
                event(null),
                event([
                    {
                        resolved_name: 'dispatchAction',
                        mangled_name: 'a',
                        source: 'src/actions.ts',
                        line: 47,
                        in_app: true,
                    },
                    { mangled_name: 'n', source: 'node_modules/react/index.js', line: 1, in_app: false },
                    {
                        resolved_name: 'onShareClick',
                        source: 'https://example.com/static/FileRow.tsx',
                        line: 88,
                        in_app: true,
                    },
                    {
                        resolved_name: null,
                        mangled_name: 'openShareModal',
                        source: 'shareLinkModal.tsx',
                        line: 142,
                        in_app: true,
                    },
                ]),
            ],
            2
        )
        expect(result).toEqual({
            frames: [
                { functionName: 'openShareModal', location: 'shareLinkModal.tsx:142' },
                { functionName: 'onShareClick', location: 'FileRow.tsx:88' },
            ],
            total: 3,
        })
    })

    test('says so when no event has a stack', () => {
        expect(issueFrames([event(null), event([])], 3)).toEqual({ frames: [], total: 0 })
    })
})

test('sampleSessions keeps the newest event of each recorded session', () => {
    const events: IssueEventApi[] = [
        {
            timestamp: '2026-10-20T11:50:00Z',
            properties: { $session_id: 'session-a', $browser: 'Chrome', $os: 'macOS' },
        },
        { timestamp: '2026-10-20T11:40:00Z', properties: { $session_id: null } },
        { timestamp: '2026-10-20T11:30:00Z', properties: { $session_id: 'session-a', $browser: 'Chrome' } },
        { timestamp: '2026-10-20T11:20:00Z', properties: { $session_id: 'session-b', $os: 'iOS' } },
        { timestamp: '2026-10-20T11:10:00Z', properties: { $session_id: 'session-c' } },
    ]
    expect(sampleSessions(events, 2)).toEqual([
        { sessionId: 'session-a', at: '2026-10-20T11:50:00Z', platform: 'Chrome on macOS' },
        { sessionId: 'session-b', at: '2026-10-20T11:20:00Z', platform: 'iOS' },
    ])
})

describe('breakdownRows', () => {
    test('uses the path when there is one, and shares of all occurrences', () => {
        const rows = breakdownRows({
            occurrences: 200,
            sample_session_ids: [],
            top_values: {
                path: [{ value: '/files/:id', count: 142 }],
                url: [{ value: 'https://example.com/files/1', count: 142 }],
                browser: [
                    { value: 'Chrome', count: 128 },
                    { value: 'Safari', count: 60 },
                    { value: 'Firefox', count: 8 },
                    { value: 'Edge', count: 4 },
                ],
            },
        })
        expect(rows).toEqual([
            { key: 'location', label: 'Path', values: [{ value: '/files/:id', percent: 71 }] },
            {
                key: 'browser',
                label: 'Browser',
                values: [
                    { value: 'Chrome', percent: 64 },
                    { value: 'Safari', percent: 30 },
                    { value: 'Firefox', percent: 4 },
                ],
            },
        ])
    })

    test('falls back to the URL for backend SDKs and is empty without occurrences', () => {
        expect(
            breakdownRows({
                occurrences: 10,
                sample_session_ids: [],
                top_values: { url: [{ value: 'https://example.com/api', count: 10 }] },
            })[0]?.label
        ).toBe('URL')
        expect(breakdownRows({ occurrences: 0, sample_session_ids: [], top_values: {} })).toEqual([])
    })
})

test.each([
    [
        { direction: 'increasing', change_percent: 45 },
        { text: 'Up 45%', rising: true },
    ],
    [
        { direction: 'decreasing', change_percent: -30 },
        { text: 'Down 30%', rising: false },
    ],
    [{ direction: 'new' }, { text: 'New in this window', rising: true }],
    [undefined, null],
] as const)('trendCaption(%j)', (trend, expected) => {
    expect(trendCaption(trend)).toEqual(expected)
})
