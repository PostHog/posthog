import type { ThreadItem } from '../types/streamTypes'
import { computeTurnTrailers, mapRowsToRevealGroup } from './turnTrailers'

function item(type: ThreadItem['type'], id: string, text?: string): ThreadItem {
    return { id, type, text }
}

describe('turnTrailers', () => {
    it('assigns stable ordinals, per-turn text, trace ids, and timestamps across multiple turns', () => {
        const trailers = computeTurnTrailers([
            item('human_message', 'h0', 'q1'),
            item('assistant_message', 'a0', 'first answer'),
            { ...item('turn_separator', 'turn-0'), traceId: 'trace-a', startedAt: 1700000000000 },
            item('human_message', 'h1', 'q2'),
            item('assistant_thought', 't0', 'thinking'),
            item('assistant_message', 'a1', 'second answer'),
            item('assistant_message', 'a2', 'continued'),
            item('turn_separator', 'turn-1'),
        ])

        expect(trailers.get('turn-0')).toEqual({
            turnIndex: 0,
            isLastTurn: false,
            turnText: 'first answer',
            traceId: 'trace-a',
            timestamp: 1700000000000,
        })
        expect(trailers.get('turn-1')).toEqual({
            turnIndex: 1,
            isLastTurn: true,
            turnText: 'second answer\n\ncontinued',
            traceId: undefined,
        })
    })

    it("does not leak a crashed turn's text into the next completed turn", () => {
        // A crashed turn never emits its separator; the next human message starts a fresh turn.
        const trailers = computeTurnTrailers([
            item('human_message', 'h0', 'q1'),
            item('assistant_message', 'a0', 'crashed partial answer'),
            item('error', 'e0'),
            item('human_message', 'h1', 'q2'),
            item('assistant_message', 'a1', 'clean answer'),
            item('turn_separator', 'turn-0'),
        ])

        expect(trailers.get('turn-0')).toEqual({ turnIndex: 0, isLastTurn: true, turnText: 'clean answer' })
    })

    it('ignores a duplicate turn-end marker with no answer behind it', () => {
        const trailers = computeTurnTrailers([
            item('human_message', 'h0', 'q1'),
            item('assistant_message', 'a0', 'answer'),
            item('turn_separator', 'turn-0'),
            item('turn_separator', 'turn-1'),
        ])
        expect([...trailers.keys()]).toEqual(['turn-0'])
        expect(trailers.get('turn-0')?.isLastTurn).toBe(true)
    })

    it('returns an empty map for a thread with no completed turns', () => {
        const trailers = computeTurnTrailers([
            item('human_message', 'h0', 'q1'),
            item('assistant_message', 'a0', 'still streaming'),
        ])
        expect(trailers.size).toBe(0)
    })

    it('maps answer rows to their turn separator, human messages to themselves, and skips unfinished rows', () => {
        const membership = mapRowsToRevealGroup([
            item('human_message', 'h0'),
            item('assistant_message', 'a0'),
            item('turn_separator', 'turn-0'),
            item('human_message', 'h1'),
            item('assistant_thought', 't1'),
            item('assistant_message', 'a1'),
            item('turn_separator', 'turn-1'),
            item('human_message', 'h2'),
            item('assistant_message', 'a2'),
        ])

        expect(Object.fromEntries(membership)).toEqual({
            h0: 'h0',
            a0: 'turn-0',
            h1: 'h1',
            t1: 'turn-1',
            a1: 'turn-1',
            h2: 'h2',
        })
    })
})
