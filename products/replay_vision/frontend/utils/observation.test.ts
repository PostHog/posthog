import type { ReplayObservationApi } from '../generated/api.schemas'
import { readFixedTags, readFreeformTags, readModelOutput, readScore, readTags, readVerdict } from './observation'

function makeObservation(modelOutput: Record<string, unknown> | null | undefined): ReplayObservationApi {
    return {
        id: 'o1',
        scanner_result:
            modelOutput === undefined ? undefined : ({ model_output: modelOutput } as Record<string, unknown>),
    } as unknown as ReplayObservationApi
}

describe('readModelOutput', () => {
    it('returns the model_output object when present', () => {
        expect(readModelOutput(makeObservation({ score: 7 }))).toEqual({ score: 7 })
    })

    it('returns null when scanner_result is absent', () => {
        expect(readModelOutput(makeObservation(undefined))).toBeNull()
    })

    it.each([null, 'hello', 42, true])('returns null when model_output is %p', (badShape) => {
        expect(readModelOutput(makeObservation(badShape as Record<string, unknown> | null))).toBeNull()
    })
})

describe('readScore', () => {
    it('returns the numeric score', () => {
        expect(readScore(makeObservation({ score: 7.5 }))).toBe(7.5)
    })

    it.each(['7', null, undefined, true, [1, 2]])('returns null for non-numeric score %p', (badScore) => {
        expect(readScore(makeObservation({ score: badScore }))).toBeNull()
    })

    it('returns null when model_output is absent', () => {
        expect(readScore(makeObservation(undefined))).toBeNull()
    })
})

describe('readVerdict', () => {
    it.each(['yes', 'no', 'inconclusive'] as const)('accepts %s', (verdict) => {
        expect(readVerdict(makeObservation({ verdict }))).toBe(verdict)
    })

    it.each(['Yes', 'YES', 'maybe', '', 1, null])('rejects non-canonical verdict %p', (bad) => {
        expect(readVerdict(makeObservation({ verdict: bad }))).toBeNull()
    })
})

describe('readFixedTags / readFreeformTags / readTags', () => {
    it('returns the fixed tag array', () => {
        expect(readFixedTags(makeObservation({ tags: ['bug', 'frustration'] }))).toEqual(['bug', 'frustration'])
    })

    it('filters non-string entries from the fixed tag array', () => {
        expect(readFixedTags(makeObservation({ tags: ['bug', 42, null, 'frustration'] }))).toEqual([
            'bug',
            'frustration',
        ])
    })

    it('returns an empty array when tags is missing or wrong shape', () => {
        expect(readFixedTags(makeObservation({}))).toEqual([])
        expect(readFixedTags(makeObservation({ tags: 'bug' }))).toEqual([])
        expect(readFixedTags(makeObservation(undefined))).toEqual([])
    })

    it('reads freeform tags from tags_freeform', () => {
        expect(readFreeformTags(makeObservation({ tags_freeform: ['custom'] }))).toEqual(['custom'])
    })

    it('concatenates fixed then freeform in readTags', () => {
        expect(readTags(makeObservation({ tags: ['bug'], tags_freeform: ['custom', 'note'] }))).toEqual([
            'bug',
            'custom',
            'note',
        ])
    })
})
