import type Stripe from 'stripe'

import { PostHogClient } from '../client'

describe('PostHogClient', () => {
    const jsonResponse = (status: number, body: unknown): Response =>
        ({
            ok: status >= 200 && status < 300,
            status,
            json: async () => body,
            text: async () => JSON.stringify(body),
        }) as Response

    const makeStripe = (): Stripe => ({ apps: { secrets: { create: jest.fn().mockResolvedValue({}) } } }) as any

    const makeClient = (stripe: Stripe = makeStripe()): PostHogClient =>
        new PostHogClient({
            baseUrl: 'https://us.posthog.com',
            accessToken: 'stale-token',
            refreshToken: 'refresh-token',
            stripe,
            clientId: 'client-id',
        })

    let fetchMock: jest.Mock

    beforeEach(() => {
        fetchMock = jest.fn()
        global.fetch = fetchMock as unknown as typeof fetch
    })

    it.each([401, 403])('refreshes the access token and retries once after a %s', async (status) => {
        fetchMock
            .mockResolvedValueOnce(jsonResponse(status, { detail: 'Access token has expired.' }))
            .mockResolvedValueOnce(jsonResponse(200, { access_token: 'fresh-token' }))
            .mockResolvedValueOnce(jsonResponse(200, { results: [{ key: 'my-flag', deleted: false }] }))

        const flags = await makeClient().fetchFeatureFlags('123')

        expect(flags).toEqual([{ key: 'my-flag', deleted: false }])
        expect(fetchMock).toHaveBeenCalledTimes(3)
        expect(fetchMock.mock.calls[1][0]).toBe('https://us.posthog.com/oauth/token/')
        expect((fetchMock.mock.calls[2][1].headers as Record<string, string>).Authorization).toBe('Bearer fresh-token')
    })

    it('persists the rotated refresh token so the next session starts with fresh credentials', async () => {
        const stripe = makeStripe()
        fetchMock
            .mockResolvedValueOnce(jsonResponse(403, { detail: 'Access token has expired.' }))
            .mockResolvedValueOnce(jsonResponse(200, { access_token: 'fresh-token', refresh_token: 'next-refresh' }))
            .mockResolvedValueOnce(jsonResponse(200, { results: [] }))

        await makeClient(stripe).fetchFeatureFlags('123')

        expect(stripe.apps.secrets.create).toHaveBeenCalledWith(
            expect.objectContaining({ name: 'posthog_refresh_token', payload: 'next-refresh' })
        )
    })

    it('does not refresh when the request succeeds', async () => {
        fetchMock.mockResolvedValueOnce(jsonResponse(200, { results: [] }))

        await makeClient().fetchFeatureFlags('123')

        expect(fetchMock).toHaveBeenCalledTimes(1)
    })
})
