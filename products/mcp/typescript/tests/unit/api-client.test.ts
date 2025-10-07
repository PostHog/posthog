import { ApiClient } from '@/api/client'
import { describe, expect, it } from 'vitest'

describe('ApiClient', () => {
    it('should create ApiClient with required config', () => {
        const client = new ApiClient({
            apiToken: 'test-token',
            baseUrl: 'https://example.com',
        })

        expect(client).toBeInstanceOf(ApiClient)
    })

    it('should use custom baseUrl when provided', () => {
        const customUrl = 'https://custom.example.com'
        const client = new ApiClient({
            apiToken: 'test-token',
            baseUrl: customUrl,
        })

        const baseUrl = (client as any).baseUrl
        expect(baseUrl).toBe(customUrl)
    })

    it('should build correct headers', () => {
        const client = new ApiClient({
            apiToken: 'test-token-123',
            baseUrl: 'https://example.com',
        })

        const headers = (client as any).buildHeaders()
        expect(headers).toEqual({
            Authorization: 'Bearer test-token-123',
            'Content-Type': 'application/json',
        })
    })
})
