import fetch, { Headers, RequestInit, Response } from 'node-fetch'

import { logger } from '../logger'
import { ResolvedRevision, ResolvedRevisionSchema, SecretsResponse, SecretsResponseSchema } from './types'

export interface InternalApiClientConfig {
    baseUrl: string
    /** Shared signing key checked by Django middleware (or set to undefined for mTLS deployments). */
    sharedKey?: string
    /** AbortController-style timeout. */
    timeoutMs?: number
}

/**
 * Talks to Django for the two endpoints declared in the agent-platform plan:
 *   - GET  /internal/agents/applications/resolve
 *   - POST /internal/agents/secrets/{app_id}/decrypt
 *
 * Both live behind internal-only scopes and are not exposed in the public API.
 */
export class InternalApiClient {
    constructor(private readonly config: InternalApiClientConfig) {}

    /** Resolve a domain or application id to the live revision + manifest. */
    async resolve(input: { domain?: string; applicationId?: string }): Promise<ResolvedRevision | null> {
        const params = new URLSearchParams()
        if (input.domain) {
            params.set('domain', input.domain)
        }
        if (input.applicationId) {
            params.set('application_id', input.applicationId)
        }
        const url = `${this.config.baseUrl}/internal/agents/applications/resolve?${params.toString()}`

        const response = await this.fetchWithAuth(url, { method: 'GET' })
        if (response.status === 404) {
            return null
        }
        if (!response.ok) {
            throw new Error(`internal-api resolve failed: ${response.status} ${await response.text()}`)
        }
        const body = (await response.json()) as unknown
        return ResolvedRevisionSchema.parse(body)
    }

    /** Decrypt a set of named secrets for an application. Audit-logged on the Django side. */
    async decryptSecrets(applicationId: string, names: string[]): Promise<SecretsResponse> {
        const url = `${this.config.baseUrl}/internal/agents/secrets/${encodeURIComponent(applicationId)}/decrypt`
        const response = await this.fetchWithAuth(url, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ names }),
        })
        if (!response.ok) {
            throw new Error(`internal-api decryptSecrets failed: ${response.status} ${await response.text()}`)
        }
        const body = (await response.json()) as unknown
        return SecretsResponseSchema.parse(body)
    }

    private async fetchWithAuth(url: string, init: RequestInit): Promise<Response> {
        const headers = new Headers(init.headers ?? {})
        if (this.config.sharedKey) {
            headers.set('x-internal-key', this.config.sharedKey)
        }
        const controller = new AbortController()
        const timeout = this.config.timeoutMs ?? 5_000
        const timer = setTimeout(() => controller.abort(), timeout)
        try {
            return await fetch(url, { ...init, headers, signal: controller.signal })
        } catch (err) {
            logger.error('internal-api request failed', { url, error: String(err) })
            throw err
        } finally {
            clearTimeout(timer)
        }
    }
}
