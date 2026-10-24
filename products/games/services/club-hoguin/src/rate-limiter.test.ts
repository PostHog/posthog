import { RateLimiter } from './rate-limiter'

describe('RateLimiter', () => {
    it('refuses a key after its burst, lets it back in as time passes, and does not count other keys', () => {
        const limiter = new RateLimiter(10, 3)

        expect([1, 2, 3, 4].map(() => limiter.allow('flood', 0))).toEqual([true, true, true, false])
        expect(limiter.allow('someone-else', 0)).toBe(true)

        expect(limiter.allow('flood', 100)).toBe(true)
        expect(limiter.allow('flood', 100)).toBe(false)
    })
})
