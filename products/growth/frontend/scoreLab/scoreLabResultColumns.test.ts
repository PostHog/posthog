import { ScoreLabRunRow } from './scoreLabLogic'
import { deriveOutputColumns } from './scoreLabResultColumns'

describe('deriveOutputColumns', () => {
    it('returns no columns for legacy verdict rows', () => {
        const rows: ScoreLabRunRow[] = [
            { company: 'Acme', domain: 'acme.com', verdict: 'true', confidence: '0.9', reasoning: 'Because' },
        ]
        expect(deriveOutputColumns(rows)).toEqual([])
    })

    it('derives one column per output key, typed from the first value seen and ordered by first appearance', () => {
        const rows: ScoreLabRunRow[] = [
            {
                company: 'Acme',
                domain: 'acme.com',
                outputs: { ai_pilled: true, confidence: 0.9, reasoning: 'Because' },
            },
            { company: 'Widgets Inc', domain: null, outputs: null, error: 'LLM timeout' },
        ]
        expect(deriveOutputColumns(rows)).toEqual([
            { key: 'ai_pilled', type: 'boolean' },
            { key: 'confidence', type: 'number' },
            { key: 'reasoning', type: 'string' },
        ])
    })

    it('ignores error rows with null outputs when deriving columns', () => {
        const rows: ScoreLabRunRow[] = [{ company: 'Acme', domain: null, outputs: null, error: 'LLM timeout' }]
        expect(deriveOutputColumns(rows)).toEqual([])
    })
})
