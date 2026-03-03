import { beforeEach, describe, expect, it, vi } from 'vitest'

import { handleRegister } from '@/handlers/register'

import { createMockKV } from './helpers'

const mockKV = createMockKV()

beforeEach(() => {
    vi.clearAllMocks()
})

describe('handleRegister', () => {
    it('dual-registers on both US and EU and stores the mapping', async () => {
        const usClientId = 'us_client_abc123'
        const euClientId = 'eu_client_def456'

        vi.stubGlobal(
            'fetch',
            vi.fn().mockImplementation((url: string) => {
                if (new URL(url).hostname === 'us.posthog.com') {
                    return Promise.resolve(
                        new Response(JSON.stringify({ client_id: usClientId, client_name: 'Test App' }), {
                            status: 201,
                            headers: { 'Content-Type': 'application/json' },
                        })
                    )
                }
                return Promise.resolve(
                    new Response(JSON.stringify({ client_id: euClientId, client_name: 'Test App' }), {
                        status: 201,
                        headers: { 'Content-Type': 'application/json' },
                    })
                )
            })
        )

        const request = new Request('https://oauth.posthog.com/oauth/register/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_name: 'Test App', redirect_uris: ['http://localhost:3000/callback'] }),
        })

        const response = await handleRegister(request, mockKV)
        const data = (await response.json()) as Record<string, unknown>

        expect(response.status).toBe(201)
        expect(data.client_id).toBe(usClientId)
        expect(vi.mocked(mockKV.put)).toHaveBeenCalledOnce()

        const storedMapping = JSON.parse(vi.mocked(mockKV.put).mock.calls[0]![1] as string)
        expect(storedMapping.us_client_id).toBe(usClientId)
        expect(storedMapping.eu_client_id).toBe(euClientId)
    })

    it('returns error when one region fails', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn().mockImplementation((url: string) => {
                if (new URL(url).hostname === 'us.posthog.com') {
                    return Promise.resolve(
                        new Response(JSON.stringify({ client_id: 'us_abc', client_name: 'Test' }), {
                            status: 201,
                            headers: { 'Content-Type': 'application/json' },
                        })
                    )
                }
                return Promise.resolve(
                    new Response(JSON.stringify({ error: 'server_error' }), {
                        status: 500,
                        headers: { 'Content-Type': 'application/json' },
                    })
                )
            })
        )

        const request = new Request('https://oauth.posthog.com/oauth/register/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_name: 'Test', redirect_uris: ['http://localhost:3000/callback'] }),
        })

        const response = await handleRegister(request, mockKV)
        expect(response.status).toBe(500)
        expect(vi.mocked(mockKV.put)).not.toHaveBeenCalled()
    })

    it('returns error when both registrations fail', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn().mockImplementation(() =>
                Promise.resolve(
                    new Response(JSON.stringify({ error: 'invalid_client_metadata' }), {
                        status: 400,
                        headers: { 'Content-Type': 'application/json' },
                    })
                )
            )
        )

        const request = new Request('https://oauth.posthog.com/oauth/register/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_name: '' }),
        })

        const response = await handleRegister(request, mockKV)
        expect(response.status).toBe(400)
        expect(vi.mocked(mockKV.put)).not.toHaveBeenCalled()
    })
})
