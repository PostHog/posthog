import type { HighlightFeedItemApi } from '../generated/api.schemas'
import { type HighlightPicksStaleReason, resolveHighlightPicksStaleReason } from './highlightPicksStaleState'

const now = new Date('2026-10-16T12:00:00Z')
const pick = (daysAgo: number, viewed: boolean): HighlightFeedItemApi =>
    ({
        observation: { created_at: new Date(now.getTime() - daysAgo * 86_400_000).toISOString(), viewed },
    }) as unknown as HighlightFeedItemApi

describe('resolveHighlightPicksStaleReason', () => {
    it.each<[string, HighlightFeedItemApi[], any, string[], HighlightPicksStaleReason | null]>([
        ['no picks, so the empty state owns it', [], 'no-scanners', [], null],
        ['a fresh unwatched pick', [pick(0.5, false)], 'quiet-window', [], null],
        ['every pick watched but recent', [pick(1, true)], 'quiet-window', [], 'caught-up'],
        ['nothing newer than two days', [pick(3, false)], 'quiet-window', [], 'quiet-week'],
        ['a block before anything else', [pick(3, true)], 'all-capped', ['a'], 'all-capped'],
        ['an exhausted quota', [pick(1, true)], 'quota-exhausted', [], 'quota-exhausted'],
        ['a drought before a quiet week', [pick(3, false)], 'quiet-window', ['a'], 'drought'],
        [
            'one fresh unwatched pick among old watched ones',
            [pick(5, true), pick(0.2, false)],
            'quiet-window',
            [],
            null,
        ],
    ])('reads %s', (_name, picks, blockReason, droughtScannerIds, expected) => {
        expect(resolveHighlightPicksStaleReason({ picks, blockReason, droughtScannerIds, now })).toBe(expected)
    })
})
