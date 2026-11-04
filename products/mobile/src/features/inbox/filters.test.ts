import type { InboxItem } from '@/model/types'

import {
    applyInboxFilters,
    DEFAULT_INBOX_FILTERS,
    type InboxFilters,
    type InboxSort,
    isDefaultInboxFilters,
    type SourceFilterKey,
    sourceFilterOptionsFor,
} from './filters'

const NOW = Date.parse('2026-10-19T12:00:00Z')
const HOUR = 3_600_000

function item(id: string, overrides: Partial<InboxItem> = {}): InboxItem {
    return {
        id,
        reportId: id,
        title: id,
        sourceProduct: 'error_tracking',
        sourceLabel: 'Error',
        sources: ['error_tracking'],
        accent: 'alert',
        createdAt: new Date(NOW - HOUR).toISOString(),
        updatedAt: new Date(NOW - HOUR).toISOString(),
        modelScore: null,
        state: 'open',
        needsInput: false,
        read: false,
        ...overrides,
    }
}

function ids(items: readonly InboxItem[]): string[] {
    return items.map((entry) => entry.id)
}

function filters(overrides: Partial<InboxFilters>): InboxFilters {
    return { ...DEFAULT_INBOX_FILTERS, ...overrides }
}

describe('inbox filters', () => {
    const bySource = [
        item('error_tracking', { sources: ['error_tracking'] }),
        item('sentry', { sources: ['sentry'] }),
        item('scout_rollbar', { sources: ['signals_scout', 'rollbar'] }),
        item('freshdesk', { sources: ['freshdesk'] }),
        item('replay_vision', { sources: ['replay_vision'] }),
        item('no_sources', { sources: [] }),
        item('unknown', { sources: ['brand_new_source'] }),
    ]

    test.each<[SourceFilterKey[], string[]]>([
        [['error'], ['error_tracking', 'sentry', 'scout_rollbar']],
        [['report'], ['scout_rollbar', 'no_sources', 'unknown']],
        [['support'], ['freshdesk']],
        [
            ['session_replay', 'support'],
            ['freshdesk', 'replay_vision'],
        ],
        [[], ids(bySource)],
    ])('the source filter %j keeps %j', (sources, expected) => {
        expect(ids(applyInboxFilters(bySource, filters({ sources }), NOW))).toEqual(expected)
    })

    test('the created window keeps a report created exactly at its start and drops an older one', () => {
        const items = [
            item('at_start', { createdAt: new Date(NOW - 24 * HOUR).toISOString() }),
            item('just_before', { createdAt: new Date(NOW - 24 * HOUR - 1).toISOString() }),
        ]
        expect(ids(applyInboxFilters(items, filters({ createdWindow: '24h' }), NOW))).toEqual(['at_start'])
        expect(ids(applyInboxFilters(items, filters({ createdWindow: 'any' }), NOW))).toEqual([
            'at_start',
            'just_before',
        ])
    })

    const ranked = [
        item('a', { createdAt: '2026-10-15T00:00:00Z', updatedAt: '2026-10-18T00:00:00Z', modelScore: null }),
        item('b', { createdAt: '2026-10-17T00:00:00Z', updatedAt: '2026-10-16T00:00:00Z', modelScore: 0.2 }),
        item('c', { createdAt: '2026-10-16T00:00:00Z', updatedAt: '2026-10-18T00:00:00Z', modelScore: 0.7 }),
        item('d', { createdAt: '2026-10-14T00:00:00Z', updatedAt: '2026-10-17T00:00:00Z', modelScore: 0.2 }),
    ]

    test.each<[InboxSort, string[]]>([
        ['recommended', ['a', 'b', 'c', 'd']],
        ['last_updated', ['a', 'c', 'd', 'b']],
        ['newest', ['b', 'c', 'a', 'd']],
        ['oldest', ['d', 'a', 'c', 'b']],
        ['model_score', ['c', 'b', 'd', 'a']],
    ])('sorts by %s, keeping ranking order on ties', (sort, expected) => {
        expect(ids(applyInboxFilters(ranked, filters({ sort }), NOW))).toEqual(expected)
    })

    test('offers each matched source group once, plus a selected group with no matches, in option order', () => {
        const items = [item('sentry', { sources: ['sentry'] }), item('error', { sources: ['error_tracking'] })]
        expect(sourceFilterOptionsFor(items, ['linear']).map((option) => option.key)).toEqual(['error', 'linear'])
    })

    test.each<[Partial<InboxFilters>, boolean]>([
        [{}, true],
        [{ sort: 'newest' }, false],
        [{ createdWindow: '7d' }, false],
        [{ sources: ['github'] }, false],
    ])('isDefaultInboxFilters(%j) is %s', (overrides, expected) => {
        expect(isDefaultInboxFilters(filters(overrides))).toBe(expected)
    })
})
