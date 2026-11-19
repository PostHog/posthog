import { buildFeedCards, type KeyOverride, nearestMoment, nextCardIndex } from './feedCards'
import type { FeedItem, Moment } from './feedModel'

function moment(startSeconds: number, endSeconds: number): Moment {
    return {
        key: `m${startSeconds}`,
        kind: 'rageclick',
        anchorSeconds: startSeconds,
        startSeconds,
        endSeconds,
        label: '',
    }
}

function item(sessionId: string, ongoing = false): FeedItem {
    return { recording: { sessionId, ongoing } } as unknown as FeedItem
}

const MOMENTS: Record<string, Moment[]> = {
    a: [moment(0, 20), moment(60, 80), moment(120, 140)],
    b: [moment(10, 30)],
    c: [moment(5, 25), moment(40, 60)],
}
const ITEMS = [item('a'), item('b', true), item('c')]
const momentsFor = (entry: FeedItem): Moment[] => MOMENTS[entry.recording.sessionId] ?? []

describe('feed cards', () => {
    test.each([
        ['no override', undefined, ['a:0', 'a:1', 'a:2']],
        ['the on-screen key moves to a later moment', { ordinal: 2, key: 'a:0' }, ['a:2', 'a:1', 'a:0']],
        ['a key from a longer list keeps its slot', { ordinal: 1, key: 'a:5' }, ['a:0', 'a:5', 'a:2']],
    ] as const)('moment cards, %s, keep unique keys', (_name, override, keys) => {
        const overrides = new Map<string, KeyOverride>(override ? [['a', override]] : [])
        const cards = buildFeedCards(ITEMS, 'moment', momentsFor, overrides)
        expect(cards.filter((card) => card.item.recording.sessionId === 'a').map((card) => card.key)).toEqual(keys)
        expect(new Set(cards.map((card) => card.key)).size).toBe(cards.length)
        expect(cards.map((card) => card.index)).toEqual(cards.map((_card, position) => position))
    })

    test('full recording has one card per recording, under the key of the card that was on screen', () => {
        const cards = buildFeedCards(ITEMS, 'session', momentsFor, new Map([['a', { ordinal: 2, key: 'a:2' }]]))
        expect(cards.map((card) => card.key)).toEqual(['a:2', 'b:0', 'c:0'])
    })

    test.each([
        ['inside a moment', 65, 1],
        ['between two moments, nearer the later one', 55, 1],
        ['between two moments, nearer the earlier one', 25, 0],
        ['after the last moment', 300, 2],
    ])('the moment nearest a time %s', (_name, seconds, expected) => {
        expect(nearestMoment(MOMENTS.a as Moment[], seconds)).toBe(expected)
    })

    test.each([
        ['the next moment of the same recording', 0, 1],
        ['past a recording still in progress to the next one', 2, 4],
        ['nothing after the last card', 5, null],
    ])('after a card, playback goes to %s', (_name, index, expected) => {
        const cards = buildFeedCards(ITEMS, 'moment', momentsFor, new Map())
        expect(nextCardIndex(cards, index, () => true, 3)).toBe(expected)
    })
})
