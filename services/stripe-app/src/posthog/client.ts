import Stripe from 'stripe'

import { logger } from '../logger'
import { saveCredentials } from './auth'
import type {
    ListResponse,
    PostHogCustomerJourney,
    PostHogExperiment,
    PostHogFeatureFlag,
    PostHogInsight,
    WebOverviewItem,
} from './types'

const IGNORED_EVENTS = ['$feature_flag_called', '$pageleave', '$groupidentify', '$set', '$opt_in']
const IGNORED_EVENTS_SQL = IGNORED_EVENTS.map((e) => `'${e}'`).join(', ')

export interface PostHogClientOptions {
    baseUrl: string
    accessToken: string
    refreshToken: string
    stripe: Stripe
    clientId: string
}

export class PostHogClient {
    readonly baseUrl: string
    private clientId: string
    private accessToken: string
    private refreshToken: string
    private stripe: Stripe

    constructor({ baseUrl, accessToken, refreshToken, stripe, clientId }: PostHogClientOptions) {
        this.baseUrl = baseUrl
        this.clientId = clientId
        this.accessToken = accessToken
        this.refreshToken = refreshToken
        this.stripe = stripe
    }

    async fetchFeatureFlags(projectId: string): Promise<PostHogFeatureFlag[]> {
        const path = `/api/projects/${encodeURIComponent(projectId)}/feature_flags/?limit=25&order=-updated_at`
        logger.debug('Fetching feature flags', path)
        const body = await this.getJson<ListResponse<PostHogFeatureFlag>>(path)
        return body.results.filter((f: PostHogFeatureFlag) => !f.deleted)
    }

    async fetchAllFeatureFlags(projectId: string, onPage: (page: PostHogFeatureFlag[]) => void): Promise<void> {
        const firstPath = `/api/projects/${encodeURIComponent(projectId)}/feature_flags/?limit=100&order=-updated_at`
        await this.streamAllPages<PostHogFeatureFlag>(firstPath, (page) => {
            onPage(page.filter((f) => !f.deleted))
        })
    }

    async fetchAllExperiments(projectId: string, onPage: (page: PostHogExperiment[]) => void): Promise<void> {
        const firstPath = `/api/projects/${encodeURIComponent(projectId)}/experiments/?limit=100&order=-updated_at`
        await this.streamAllPages<PostHogExperiment>(firstPath, (page) => {
            onPage(page.filter((e) => !e.archived))
        })
    }

    private async streamAllPages<T>(firstPath: string, onPage: (page: T[]) => void): Promise<void> {
        let nextPath: string | null = firstPath
        while (nextPath) {
            const body: ListResponse<T> = await this.getJson<ListResponse<T>>(nextPath)
            onPage(body.results)
            nextPath = body.next ? this.toRelativePath(body.next) : null
        }
    }

    private toRelativePath(url: string): string {
        try {
            const parsed = new URL(url)
            return parsed.pathname + parsed.search
        } catch {
            return url
        }
    }

    async fetchCustomerJourneys(projectId: string): Promise<PostHogCustomerJourney[]> {
        const path = `/api/environments/${encodeURIComponent(projectId)}/customer_journeys/`
        logger.debug('Fetching customer journeys', path)
        const body = await this.getJson<ListResponse<PostHogCustomerJourney>>(path)
        return body.results
    }

    async fetchInsight(projectId: string, insightId: number): Promise<PostHogInsight> {
        const path = `/api/projects/${encodeURIComponent(projectId)}/insights/${insightId}/`
        logger.debug('Fetching insight', path)
        return this.getJson<PostHogInsight>(path)
    }

    async fetchEventTrends(projectId: string, days: number): Promise<{ date: string; count: number }[]> {
        const path = `/api/projects/${encodeURIComponent(projectId)}/query/`
        logger.debug('Fetching event trends', path)

        const bucket = days > 31 ? 'toStartOfWeek' : 'toStartOfDay'
        const body = await this.postJson<{ results: [number, string][] }>(path, {
            query: {
                kind: 'HogQLQuery',
                query: `SELECT count() AS count, ${bucket}(timestamp) AS bucket
                         FROM events
                         WHERE timestamp >= today() - INTERVAL ${days} DAY
                         GROUP BY bucket
                         ORDER BY bucket`,
            },
        })
        return body.results.map(([count, bucket]: [number, string]) => ({ date: bucket, count }))
    }

    async fetchTopEvents(projectId: string, days: number, limit = 5): Promise<{ event: string; count: number }[]> {
        const path = `/api/projects/${encodeURIComponent(projectId)}/query/`
        logger.debug('Fetching top events', path)
        const body = await this.postJson<{ results: [number, string][] }>(path, {
            query: {
                kind: 'HogQLQuery',
                query: `SELECT count() AS count, event
                         FROM events
                         WHERE timestamp >= today() - INTERVAL ${days} DAY
                           AND event NOT IN (${IGNORED_EVENTS_SQL})
                         GROUP BY event
                         ORDER BY count DESC
                         LIMIT ${limit}`,
            },
        })
        return body.results.map(([count, event]: [number, string]) => ({ event, count }))
    }

    async fetchWebOverview(projectId: string, dateFrom: string): Promise<WebOverviewItem[]> {
        const path = `/api/projects/${encodeURIComponent(projectId)}/query/`
        logger.debug('Fetching web overview', path)
        const body = await this.postJson<{ results: WebOverviewItem[] }>(path, {
            query: {
                kind: 'WebOverviewQuery',
                properties: [],
                dateRange: { date_from: dateFrom },
                compareFilter: { compare: true },
                filterTestAccounts: true,
            },
        })
        return body.results
    }

    async refreshAccessToken(): Promise<void> {
        if (!this.clientId) {
            throw new Error('Cannot refresh PostHog token without a client_id')
        }

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

    private async getJson<T>(path: string): Promise<T> {
        const response = await this.request(path)
        if (!response.ok) {
            const body = await response.text().catch(() => '<unreadable>')
            throw new Error(`PostHog API ${response.status} on ${path}: ${body}`)
        }
        return (await response.json()) as T
    }

    private async postJson<T>(path: string, payload: unknown): Promise<T> {
        const response = await this.request(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
        if (!response.ok) {
            const body = await response.text().catch(() => '<unreadable>')
            throw new Error(`PostHog API ${response.status} on ${path}: ${body}`)
        }
        return (await response.json()) as T
    }

    private async request(path: string, options?: RequestInit): Promise<Response> {
        const url = `${this.baseUrl}${path}`
        const headers: Record<string, string> = {
            Authorization: `Bearer ${this.accessToken}`,
            ...(options?.headers as Record<string, string> | undefined),
        }

        let response = await fetch(url, { ...options, headers })

        // If we get a 401 and we have a client_id, try refreshing the token and retrying once.
        if (response.status === 401 && this.clientId) {
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
