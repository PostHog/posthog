import { refundBlockFor } from './refundBlock'

describe('refundBlockFor', () => {
    it('reports nothing blocked without a reason', () => {
        expect(refundBlockFor(null)).toBeNull()
        expect(refundBlockFor(undefined)).toBeNull()
    })

    it.each([
        ['out_of_period', true],
        ['no_billable_pr', false],
        ['some_new_backend_reason', false],
    ])('routes %s to support: %s', (reason, routesToSupport) => {
        expect(refundBlockFor(reason)?.routesToSupport).toBe(routesToSupport)
    })

    it('names support in the copy for a PR past its refund window', () => {
        expect(refundBlockFor('out_of_period')?.copy).toContain('Support can credit it back')
    })

    it('explains an unrecognized reason instead of showing it raw', () => {
        expect(refundBlockFor('some_new_backend_reason')?.copy).toBe("This PR can't be refunded right now")
    })
})
