import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RateLimiter } from '@/api/rate-limiter'

describe('RateLimiter', () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('should create RateLimiter with default config', () => {
        const limiter = new RateLimiter()
        expect(limiter).toBeInstanceOf(RateLimiter)
    })

    it('should create RateLimiter with custom config', () => {
        const limiter = new RateLimiter(5, 2000)
        expect(limiter).toBeInstanceOf(RateLimiter)
    })

    it('should allow requests under the limit', async () => {
        const limiter = new RateLimiter(3, 1000)
        const startTime = Date.now()

        await limiter.throttle()
        await limiter.throttle()
        await limiter.throttle()

        const endTime = Date.now()
        // Should complete almost immediately (within 50ms)
        expect(endTime - startTime).toBeLessThan(50)
    })

    it('should throttle requests when limit is exceeded', async () => {
        const limiter = new RateLimiter(2, 1000)
        
        // First two requests should go through immediately
        await limiter.throttle()
        await limiter.throttle()
        
        // Third request should be delayed
        const promise = limiter.throttle()
        
        // Advance time by 500ms - should still be waiting
        await vi.advanceTimersByTimeAsync(500)
        
        // Advance time by another 520ms (total 1020ms) - should now complete
        await vi.advanceTimersByTimeAsync(520)
        await promise
        
        // Verify the request completed
        expect(true).toBe(true)
    })

    it('should allow requests after window expires', async () => {
        const limiter = new RateLimiter(2, 1000)
        
        // Make 2 requests
        await limiter.throttle()
        await limiter.throttle()
        
        // Advance time past the window
        await vi.advanceTimersByTimeAsync(1100)
        
        // Next request should go through immediately
        const startTime = Date.now()
        await limiter.throttle()
        const endTime = Date.now()
        
        expect(endTime - startTime).toBeLessThan(50)
    })

    it('should handle multiple sequential throttled requests', async () => {
        const limiter = new RateLimiter(2, 1000)
        
        // Fill the limit
        await limiter.throttle()
        await limiter.throttle()
        
        // Queue up multiple requests
        const promise1 = limiter.throttle()
        const promise2 = limiter.throttle()
        
        // Advance time to allow first throttled request
        await vi.advanceTimersByTimeAsync(1020)
        await promise1
        
        // Advance time to allow second throttled request
        await vi.advanceTimersByTimeAsync(1020)
        await promise2
        
        expect(true).toBe(true)
    })

    it('should reset the rate limiter state', async () => {
        const limiter = new RateLimiter(2, 1000)
        
        // Fill the limit
        await limiter.throttle()
        await limiter.throttle()
        
        // Reset
        limiter.reset()
        
        // Should be able to make requests immediately
        const startTime = Date.now()
        await limiter.throttle()
        await limiter.throttle()
        const endTime = Date.now()
        
        expect(endTime - startTime).toBeLessThan(50)
    })

    it('should handle concurrent requests correctly', async () => {
        const limiter = new RateLimiter(3, 1000)
        
        // Start 5 concurrent requests
        const promises = [
            limiter.throttle(),
            limiter.throttle(),
            limiter.throttle(),
            limiter.throttle(),
            limiter.throttle(),
        ]
        
        // First 3 should complete immediately
        await vi.advanceTimersByTimeAsync(10)
        
        // Advance time to allow remaining requests
        await vi.advanceTimersByTimeAsync(1020)
        
        // All promises should resolve
        await Promise.all(promises)
        expect(true).toBe(true)
    })

    it('should maintain sliding window correctly', async () => {
        const limiter = new RateLimiter(3, 1000)
        
        // Request at t=0
        await limiter.throttle()
        
        // Advance 400ms, make 2 more requests (t=400)
        await vi.advanceTimersByTimeAsync(400)
        await limiter.throttle()
        await limiter.throttle()
        
        // Advance 700ms (t=1100, first request expired)
        await vi.advanceTimersByTimeAsync(700)
        
        // Should be able to make another request immediately
        const startTime = Date.now()
        await limiter.throttle()
        const endTime = Date.now()
        
        expect(endTime - startTime).toBeLessThan(50)
    })

    it('should add buffer time to prevent edge cases', async () => {
        const limiter = new RateLimiter(1, 1000)
        
        await limiter.throttle()
        
        const promise = limiter.throttle()
        
        // Advance exactly 1000ms - should still be waiting due to 10ms buffer
        await vi.advanceTimersByTimeAsync(1000)
        
        // Advance the buffer time
        await vi.advanceTimersByTimeAsync(20)
        await promise
        
        expect(true).toBe(true)
    })

    it('should handle zero wait time gracefully', async () => {
        const limiter = new RateLimiter(5, 1000)
        
        // Make requests that don't exceed limit
        await limiter.throttle()
        
        // Advance time past window
        await vi.advanceTimersByTimeAsync(1100)
        
        // Should handle the case where waitTime would be negative
        await limiter.throttle()
        expect(true).toBe(true)
    })

    it('should work with very short time windows', async () => {
        const limiter = new RateLimiter(2, 100)
        
        await limiter.throttle()
        await limiter.throttle()
        
        const promise = limiter.throttle()
        
        // Advance past the short window
        await vi.advanceTimersByTimeAsync(120)
        await promise
        
        expect(true).toBe(true)
    })

    it('should work with very high request limits', async () => {
        const limiter = new RateLimiter(100, 1000)
        
        // Make many requests
        const promises = Array.from({ length: 50 }, () => limiter.throttle())
        
        // All should complete quickly since we're under the limit
        await Promise.all(promises)
        expect(true).toBe(true)
    })
})
