import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    readSimilarSearchIntent,
    firstCitedTimestampMs,
    markSimilarSearchIntent,
    similarSearchQuery,
    similarSearchUrl,
} from './observationQueries'

function observation(modelOutput: Record<string, unknown> | null): ReplayObservationApi {
    return {
        id: 'obs-1',
        session_id: 'session-1',
        scanner_result: modelOutput ? { model_output: modelOutput } : null,
    } as unknown as ReplayObservationApi
}

describe('observationQueries', () => {
    it.each([
        ['a summary citation, ahead of the reasoning', { summary: 'a (t 12)', reasoning: 'c (t 5)' }, 12000],
        ['a reasoning citation when the summary has none', { summary: 'plain', reasoning: 'c (t 5)' }, 5000],
        ['nothing when nothing is cited', { summary: 'plain' }, null],
    ])('cites %s', (_name, modelOutput, expected) => {
        expect(firstCitedTimestampMs(observation(modelOutput))).toBe(expected)
    })

    it.each([
        [
            'drops citations and collapses the gap',
            { summary: 'User  rage clicked (t 12) the button' },
            'User rage clicked the button',
        ],
        ['falls back to the reasoning', { reasoning: 'Hesitated on pricing' }, 'Hesitated on pricing'],
        ['gives null when there is no prose', { summary: '   ' }, null],
    ])('%s', (_name, modelOutput, expected) => {
        expect(similarSearchQuery(observation(modelOutput))).toBe(expected)
    })

    it('cuts a long summary at a word boundary', () => {
        const query = similarSearchQuery(observation({ summary: `${'word '.repeat(80)}tail` }))
        expect(query!.length).toBeLessThanOrEqual(300)
        expect(query!.endsWith('word')).toBe(true)
    })

    it('hands the prose off to the one navigation that armed it, never through the URL', () => {
        const source = observation({ summary: 'stuck at checkout' })
        expect(similarSearchUrl(source)).toBe('/replay-vision?tab=search&similar=obs-1')

        markSimilarSearchIntent(source)
        expect(readSimilarSearchIntent('another-observation')).toBeNull()
        markSimilarSearchIntent(source)
        expect(readSimilarSearchIntent('obs-1')).toBe('stuck at checkout')
        expect(readSimilarSearchIntent('obs-1')).toBe('stuck at checkout')
    })
})
