import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    consumeSimilarSearchIntent,
    markSimilarSearchIntent,
    similarSearchQuery,
    similarSearchUrl,
    watchMomentUrl,
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
        [
            'a summary citation, ahead of the reasoning',
            { summary: 'a (t 12)', reasoning: 'c (t 5)' },
            '/replay/session-1?t=12',
        ],
        [
            'a reasoning citation when the summary has none',
            { summary: 'plain', reasoning: 'c (t 5)' },
            '/replay/session-1?t=5',
        ],
        ['the recording start when nothing is cited', { summary: 'plain' }, '/replay/session-1'],
    ])('watches at %s', (_name, modelOutput, expected) => {
        expect(watchMomentUrl(observation(modelOutput))).toBe(expected)
    })

    it.each([
        [
            'drops citations and collapses the gap',
            { summary: 'User  rage clicked (t 12) the button' },
            'User rage clicked the button',
        ],
        ['falls back to the reasoning', { reasoning: 'Hesitated on pricing' }, 'Hesitated on pricing'],
        [
            'leads with the title, as the summarizer indexes it',
            { title: 'Stalled', summary: 'Paused' },
            'Stalled Paused',
        ],
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
        expect(consumeSimilarSearchIntent('another-observation')).toBeNull()
        markSimilarSearchIntent(source)
        expect(consumeSimilarSearchIntent('obs-1')).toBe('stuck at checkout')
        expect(consumeSimilarSearchIntent('obs-1')).toBeNull()
    })
})
