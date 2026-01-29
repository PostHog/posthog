import { describe, expect, it } from 'vitest'

import {
    calculateBackoffDelay,
    formatRateLimitError,
    parseRetryAfter,
    RETRY_CONFIG,
    safeJsonParse,
} from '@/api/retry-utils'

describe('retry-utils', () => {
    describe('RETRY_CONFIG', () => {
        it('should have correct default values', () => {
            expect(RETRY_CONFIG.MAX_RETRIES).toBe(3)
            expect(RETRY_CONFIG.BASE_BACKOFF_MS).toBe(2000)
        })
    })

    describe('parseRetryAfter', () => {
        it('should return null for null input', () => {
            expect(parseRetryAfter(null)).toBeNull()
        })

        it('should parse valid delay-seconds format', () => {
            expect(parseRetryAfter('5')).toBe(5000)
            expect(parseRetryAfter('10')).toBe(10000)
            expect(parseRetryAfter('120')).toBe(120000)
        })

        it('should return null for invalid numeric values', () => {
            expect(parseRetryAfter('0')).toBeNull()
            expect(parseRetryAfter('-5')).toBeNull()
            expect(parseRetryAfter('abc')).toBeNull()
        })

        it('should parse valid HTTP-date format', () => {
            const futureDate = new Date(Date.now() + 5000).toUTCString()
            const delay = parseRetryAfter(futureDate)
            expect(delay).toBeGreaterThan(4000)
            expect(delay).toBeLessThan(6000)
        })

        it('should return 0 for past HTTP-date', () => {
            const pastDate = new Date(Date.now() - 5000).toUTCString()
            expect(parseRetryAfter(pastDate)).toBe(0)
        })

        it('should return null for invalid date format', () => {
            expect(parseRetryAfter('not a date')).toBeNull()
            expect(parseRetryAfter('2023-13-45')).toBeNull()
        })
    })

    describe('calculateBackoffDelay', () => {
        it('should calculate exponential backoff correctly', () => {
            expect(calculateBackoffDelay(0)).toBe(2000) // 2000 * 2^0
            expect(calculateBackoffDelay(1)).toBe(4000) // 2000 * 2^1
            expect(calculateBackoffDelay(2)).toBe(8000) // 2000 * 2^2
            expect(calculateBackoffDelay(3)).toBe(16000) // 2000 * 2^3
        })

        it('should use Retry-After header when provided', () => {
            expect(calculateBackoffDelay(0, '10')).toBe(10000)
            expect(calculateBackoffDelay(1, '5')).toBe(5000)
        })

        it('should fall back to exponential backoff for invalid Retry-After', () => {
            expect(calculateBackoffDelay(0, 'invalid')).toBe(2000)
            expect(calculateBackoffDelay(1, 'abc')).toBe(4000)
        })

        it('should handle HTTP-date in Retry-After header', () => {
            const futureDate = new Date(Date.now() + 7000).toUTCString()
            const delay = calculateBackoffDelay(0, futureDate)
            expect(delay).toBeGreaterThan(6000)
            expect(delay).toBeLessThan(8000)
        })
    })

    describe('safeJsonParse', () => {
        it('should parse valid JSON response', async () => {
            const response = new Response(JSON.stringify({ error: 'test error' }))
            const result = await safeJsonParse(response)
            
            expect(result.json).toEqual({ error: 'test error' })
            expect(result.text).toBe('{"error":"test error"}')
        })

        it('should handle non-JSON response', async () => {
            const response = new Response('Plain text error')
            const result = await safeJsonParse(response)
            
            expect(result.json).toBeNull()
            expect(result.text).toBe('Plain text error')
        })

        it('should handle HTML error response', async () => {
            const response = new Response('<html><body>Error</body></html>')
            const result = await safeJsonParse(response)
            
            expect(result.json).toBeNull()
            expect(result.text).toBe('<html><body>Error</body></html>')
        })

        it('should handle empty response', async () => {
            const response = new Response('')
            const result = await safeJsonParse(response)
            
            expect(result.json).toBeNull()
            expect(result.text).toBe('')
        })
    })

    describe('formatRateLimitError', () => {
        it('should format rate limit error correctly', () => {
            const message = formatRateLimitError(3, 429, '{"error":"Too many requests"}')
            expect(message).toContain('Rate limit exceeded after 3 retries')
            expect(message).toContain('Status: 429')
            expect(message).toContain('Too many requests')
        })

        it('should handle plain text error response', () => {
            const message = formatRateLimitError(3, 429, 'Rate limit exceeded')
            expect(message).toContain('Rate limit exceeded after 3 retries')
            expect(message).toContain('Status: 429')
            expect(message).toContain('Rate limit exceeded')
        })
    })
})
