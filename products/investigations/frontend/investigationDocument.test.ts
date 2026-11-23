import {
    InvestigationDocument,
    appendInvestigationRun,
    compareInvestigationResults,
    getInvestigationLink,
    investigationRunSchema,
    newInvestigation,
    removeInvestigationEvidence,
    snapshotInvestigationResult,
} from './investigationDocument'
import { investigationExample } from './investigationExample'

describe('investigation documents', () => {
    const evidence = investigationExample().evidence[0]
    const baseline = snapshotInvestigationResult(evidence, ['rate'], [[0]])

    it.each([
        [snapshotInvestigationResult(evidence, ['rate'], [[5]]), baseline, 'changed', 5],
        [snapshotInvestigationResult(evidence, ['rate'], [[0]]), baseline, 'unchanged', 0],
        [
            snapshotInvestigationResult({ ...evidence, sql: 'SELECT 5' }, ['rate'], [[5]]),
            baseline,
            'changed_query',
            null,
        ],
        [snapshotInvestigationResult(evidence, ['different_metric'], [[5]]), baseline, 'changed_query', null],
        [{ ...baseline, error: 'Query failed' }, baseline, 'error', null],
        [baseline, { ...baseline, error: 'Query failed' }, 'error', null],
        [{ ...baseline, truncated: true }, baseline, 'incomplete', null],
        [baseline, undefined, 'new', null],
    ])('compares only complete results with identical definitions (%#)', (current, previous, kind, delta) => {
        expect(compareInvestigationResults(current, previous)).toMatchObject({ kind, delta })
    })

    it.each([
        ['2026-11-01T12:30:00+01:00', '2026-11-01T12:30:00+01:00'],
        ['2026-11-01T12:30:00', '2026-11-01T12:30:00Z'],
    ])('reads a saved run timestamp %s', (at, expected) => {
        expect(investigationRunSchema.parse({ id: 'run', at, conclusion: '', results: [] }).at).toBe(expected)
    })

    it('retains the pinned baseline when old runs are evicted', () => {
        let document: InvestigationDocument = { ...newInvestigation(), baselineId: '0' }
        for (let index = 0; index < 12; index++) {
            document = appendInvestigationRun(document, {
                id: String(index),
                at: '2026-11-01T00:00:00.000Z',
                conclusion: '',
                results: [baseline],
            })
        }
        expect(document.runs.map((run) => run.id)).toEqual(['0', '3', '4', '5', '6', '7', '8', '9', '10', '11'])
    })

    it('removes dangling hypothesis references while preserving historical evidence', () => {
        const document = removeInvestigationEvidence(investigationExample(), 'conversion')
        expect(document.evidence.map((item) => item.id)).toEqual(['segments'])
        expect(document.hypotheses.flatMap((item) => item.evidenceIds)).not.toContain('conversion')
        expect(document.runs[0].results[0].evidenceId).toBe('conversion')
    })

    it('bounds snapshots and marks them as partial instead of asserting equality', () => {
        const result = snapshotInvestigationResult(
            evidence,
            ['value'],
            Array.from({ length: 51 }, (_, index) => [index])
        )
        expect(result.rows).toHaveLength(50)
        expect(compareInvestigationResults(result, result).kind).toBe('incomplete')
    })

    it.each([
        'javascript:alert(1)',
        'data:text/html,<script>alert(1)</script>',
        '//example.com',
        '/\\example.com',
        'not a url',
    ])('rejects unsafe evidence link %s', (url) => {
        expect(getInvestigationLink(url)).toBeNull()
    })

    it('never treats truncated JSON cells as complete evidence', () => {
        const result = snapshotInvestigationResult(evidence, ['payload'], [[{ detail: 'x'.repeat(2100) }]])
        expect(String(result.rows[0][0])).toHaveLength(2000)
        expect(compareInvestigationResults(result, result).kind).toBe('incomplete')
    })

    it.each(['/project/1/replay/abc', 'https://example.com/report'])('keeps supported evidence link %s', (url) => {
        expect(getInvestigationLink(url)).toBe(url)
    })
})
