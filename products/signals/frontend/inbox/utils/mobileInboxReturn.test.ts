import { getMobileInboxReturn, rememberMobileInboxReturn } from './mobileInboxReturn'

describe('mobile inbox return', () => {
    beforeEach(() => {
        window.sessionStorage.clear()
        jest.useFakeTimers()
    })
    afterEach(() => jest.useRealTimers())

    it('remembers a valid return across setup routes, only for the originating project', () => {
        rememberMobileInboxReturn(42, 'posthog')
        expect(getMobileInboxReturn(42)).toBe('posthog://inbox')
        expect(getMobileInboxReturn(43)).toBeNull()
        jest.advanceTimersByTime(60 * 60 * 1000)
        expect(getMobileInboxReturn(42)).toBeNull()
    })

    it.each(['https://example.com', 'javascript:alert(1)', '//example.com', ['posthog']])(
        'does not turn an arbitrary redirect into a return link: %s',
        (scheme) => {
            rememberMobileInboxReturn(42, scheme)
            expect(getMobileInboxReturn(42)).toBeNull()
        }
    )
})
