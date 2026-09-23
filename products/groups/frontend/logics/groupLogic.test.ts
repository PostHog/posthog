import { resolveBackNavigation } from './groupLogic'

describe('resolveBackNavigation', () => {
    it('returns the sanitized internal path and name', () => {
        expect(resolveBackNavigation({ backUrl: '/customer_analytics/accounts', backName: 'Accounts' })).toEqual({
            url: '/customer_analytics/accounts',
            name: 'Accounts',
        })
    })

    it('preserves search and hash on the internal path', () => {
        expect(
            resolveBackNavigation({ backUrl: '/customer_analytics/accounts?tab=usage#view=abc', backName: 'Accounts' })
        ).toEqual({ url: '/customer_analytics/accounts?tab=usage#view=abc', name: 'Accounts' })
    })

    it('rejects an absolute external URL (open redirect guard)', () => {
        expect(resolveBackNavigation({ backUrl: 'https://evil.com', backName: 'Accounts' })).toBeNull()
    })

    it('rejects a protocol-relative URL', () => {
        expect(resolveBackNavigation({ backUrl: '//evil.com' })).toBeNull()
    })

    it('returns null when backUrl is absent', () => {
        expect(resolveBackNavigation({})).toBeNull()
    })

    it('falls back to a default name when backName is missing', () => {
        expect(resolveBackNavigation({ backUrl: '/groups/0/acme' })).toEqual({ url: '/groups/0/acme', name: 'Back' })
    })
})
