import { type FailureKind, failureRetryGuidance, observationRetryOffer } from './types'

describe('retry guidance', () => {
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

    describe('observationRetryOffer', () => {
        it.each<[string, Parameters<typeof observationRetryOffer>[0], string, boolean, boolean]>([
            // label, status, error_reason, show, worthwhile
            ['any failed observation', 'failed', 'internal_error:boom', true, true],
            ['a failed observation with an unknown kind', 'failed', 'future_kind:msg', true, true],
            ['a discouraged failure kind, softly', 'failed', 'provider_rejected:declined', true, false],
            // no_snapshots can be a timing artifact (snapshots that finished ingesting after the scan), and the
            // backend retry endpoint accepts ineligible rows; withholding the button would strand the session.
            [
                'an ineligible observation with no snapshots',
                'ineligible',
                'no_snapshots:nothing to render',
                true,
                false,
            ],
            // no_ai_consent offers a retry too: consent can be turned on after the scan, and without the
            // button the unique (scanner, session) row would lock the session out permanently.
            ['an ineligible observation without AI consent', 'ineligible', 'no_ai_consent:consent off', true, false],
            ['a deterministic ineligibility gate', 'ineligible', 'too_short:12s long', false, false],
            ['an unknown ineligible kind', 'ineligible', 'future_gate:msg', false, false],
            ['a succeeded observation', 'succeeded', '', false, false],
            ['a running observation', 'running', '', false, false],
        ])('handles %s', (_label, status, errorReason, show, worthwhile) => {
            const offer = observationRetryOffer(status, errorReason)
            expect(offer.show).toBe(show)
            expect(offer.worthwhile).toBe(worthwhile)
        })

        it('carries a hint for the ineligible kinds it offers, so the button can say why retrying might work', () => {
            expect(observationRetryOffer('ineligible', 'no_snapshots:nothing to render').hint).not.toBeNull()
        })
    })
})
