import type { AIEnrichmentRunRow } from './aiEnrichmentLogic'
import { deriveOutputColumns, isSkippedRow, summarizeError, summarizeInputs } from './aiEnrichmentResultColumns'

const row = (outputs: AIEnrichmentRunRow['outputs'], meta?: AIEnrichmentRunRow['meta']): AIEnrichmentRunRow => ({
    company: 'Acme',
    domain: 'acme.com',
    inputs: {},
    outputs,
    ...(meta ? { meta } : {}),
})

describe('aiEnrichmentResultColumns', () => {
    describe('isSkippedRow', () => {
        it("prefers meta.skipped, the backend's authoritative flag", () => {
            expect(isSkippedRow(row({ is_ai: true }, { skipped: 'missing or empty archived payload' }))).toBe(true)
            expect(isSkippedRow(row({ is_ai: true }, {}))).toBe(false)
        })

        it('falls back to sniffing for the literal "unknown" string when meta is absent', () => {
            expect(isSkippedRow(row({ is_ai: 'unknown' }))).toBe(true)
            expect(isSkippedRow(row({ is_ai: true }))).toBe(false)
        })
    })

    describe('deriveOutputColumns', () => {
        it('derives column key and type from the first row that has each key', () => {
            const rows = [row({ is_ai: true, confidence: 0.9, reasoning: 'because' })]
            expect(deriveOutputColumns(rows)).toEqual([
                { key: 'is_ai', type: 'boolean' },
                { key: 'confidence', type: 'number' },
                { key: 'reasoning', type: 'string' },
            ])
        })

        it('skips error rows, whose outputs is null', () => {
            const rows = [row(null), row({ is_ai: false })]
            expect(deriveOutputColumns(rows)).toEqual([{ key: 'is_ai', type: 'boolean' }])
        })

        it('returns nothing for an all-error result set', () => {
            expect(deriveOutputColumns([row(null)])).toEqual([])
        })

        it('does not let an "unknown" verdict decide a boolean column\'s type', () => {
            // If the first sampled row were skipped, taking its type from the literal string
            // "unknown" would mark the whole column "string" and misrender every later row's
            // real boolean under the wrong branch.
            const rows = [row({ is_ai: 'unknown' }), row({ is_ai: true })]
            expect(deriveOutputColumns(rows)).toEqual([{ key: 'is_ai', type: 'boolean' }])
        })

        it('falls back to string for a key that is "unknown" in every sampled row', () => {
            expect(deriveOutputColumns([row({ is_ai: 'unknown' })])).toEqual([{ key: 'is_ai', type: 'string' }])
        })

        it('treats a meta.skipped row as skipped even for a field whose skipped value is null rather than "unknown"', () => {
            // Only the boolean verdict field (if any) gets the literal "unknown" string on a
            // skipped row (enrichment/labels.py's unknown_output); every other configured field
            // is just null. Without meta.skipped, a null first value would still get typed
            // "string" here (typeOfValue's default) and misrender every later row's real number.
            const skippedOutputs = { headcount: null } as unknown as AIEnrichmentRunRow['outputs']
            const rows = [row(skippedOutputs, { skipped: 'missing or empty archived payload' }), row({ headcount: 12 })]
            expect(deriveOutputColumns(rows)).toEqual([{ key: 'headcount', type: 'number' }])
        })
    })

    describe('summarizeInputs', () => {
        it('joins fields sent to the LLM into one line', () => {
            expect(summarizeInputs({ name: 'Acme', 'funding.fundingStage': 'seed' })).toBe(
                'name: Acme, funding.fundingStage: seed'
            )
        })

        it('is blank when nothing was sent (e.g. an unknown/skipped verdict)', () => {
            expect(summarizeInputs({})).toBe('')
        })
    })

    describe('summarizeError', () => {
        it('maps a recognized exception pattern to a plain-language summary', () => {
            expect(summarizeError('AuthenticationError: litellm.AuthenticationError: Incorrect API key')).toBe(
                'Authentication failed for this model. Check the API key configuration.'
            )
        })

        it('falls back to the raw error text when nothing matches', () => {
            expect(summarizeError('SomeWeirdError: unrecognized failure shape')).toBe(
                'SomeWeirdError: unrecognized failure shape'
            )
        })
    })
})
