import Stripe from 'stripe'

import { saveCredentials } from './auth'

export class PostHogClient {
    private baseUrl: string
    private clientId: string
    private accessToken: string
    private refreshToken: string
    private stripe: Stripe

    constructor(baseUrl: string, clientId: string, accessToken: string, refreshToken: string, stripe: Stripe) {
        this.baseUrl = baseUrl

        this.clientId = clientId
        this.accessToken = accessToken
        this.refreshToken = refreshToken

        this.stripe = stripe
    }

    async refreshAccessToken(): Promise<void> {
        let response: Response
        try {
            response = await fetch(`${this.baseUrl}/oauth/token/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({
                    grant_type: 'refresh_token',
                    refresh_token: this.refreshToken,
                    client_id: this.clientId,
                }),
            })
        } catch (e) {
            throw new Error(`Token refresh request failed: ${e}`)
        }

        if (!response.ok) {
            const text = await response.text().catch(() => '<unreadable body>')
            throw new Error(`Token refresh failed (${response.status}): ${text}`)
        }

        const tokenData = await response.json()

        if (!tokenData.access_token) {
            throw new Error('Token refresh response missing access_token')
        }

        this.accessToken = tokenData.access_token
        if (tokenData.refresh_token) {
            this.refreshToken = tokenData.refresh_token
        }

        // Persist rotated tokens back to Stripe's Secret Store so they survive across sessions.
        // If this fails we still have valid in-memory tokens for the current session,
        // but the next session will start with stale credentials — so we let it throw.
        await saveCredentials(this.stripe, {
            region: this.baseUrlRegion,
            accessToken: this.accessToken,
            refreshToken: this.refreshToken,
        })
    }

    async request(path: string, options?: RequestInit): Promise<Response> {
        const url = `${this.baseUrl}${path}`
        const headers = {
            Authorization: `Bearer ${this.accessToken}`,
            ...options?.headers,
        }

        let response = await fetch(url, { ...options, headers })

        // If we get a 401, try refreshing the token and retrying once
        if (response.status === 401) {
            await this.refreshAccessToken()
            headers.Authorization = `Bearer ${this.accessToken}`
            response = await fetch(url, { ...options, headers })
        }

        return response
    }

    private get baseUrlRegion(): 'us' | 'eu' {
        return this.baseUrl.includes('.eu.') ? 'eu' : 'us'
    }
}
