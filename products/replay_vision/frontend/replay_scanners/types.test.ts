import { type FailureKind, failureRetryGuidance } from './types'

describe('failureRetryGuidance', () => {
    // The retry button is always rendered; this is what decides whether we push it. Getting a kind into the wrong
    // bucket either discourages the retry that fixes it, or promises one that can only fail the same way.
    const cases: [FailureKind, boolean, boolean][] = [
        // kind, worthwhile, carries a hint
        ['provider_transient', true, false],
        ['infra_transient', true, false],
        ['rasterization_failed', true, false],
        ['orphaned', true, false],
        ['internal_error', true, false],
        ['provider_rejected', false, true],
        ['validation_failed', false, true],
    ]

    it.each(cases)('classifies %s', (kind, worthwhile, hasHint) => {
        const guidance = failureRetryGuidance(kind)
        expect(guidance.worthwhile).toBe(worthwhile)
        expect(guidance.hint !== null).toBe(hasHint)
    })

    it('offers the retry for a kind it cannot parse', () => {
        // A reason the backend added and this build doesn't know yet parses to null. Withholding the retry on no
        // evidence would strand the user, so the unknown case has to stay encouraging.
        expect(failureRetryGuidance(null)).toEqual({ worthwhile: true, hint: null })
    })
})
