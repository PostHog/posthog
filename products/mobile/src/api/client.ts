import { fetch as streamingFetch } from 'expo/fetch'

import { withAppReloadBlocked } from '@/lib/appReload'
import { isRecord } from '@/lib/records'

import { BudgetExceededError, type BudgetFamily, budgetFamilyFor, trySpend } from './budget'
import { recordServerDate } from './serverClock'

export interface ApiAuth {
    host: string
    accessToken: string | null
    projectId: number | null
    /** Changes when the user signs in or out, but not when a refresh rotates the token. */
    session: number
}

export interface AuthProvider {
    getAuth: () => ApiAuth
    refreshAccessToken: () => Promise<string | null>
}

let provider: AuthProvider | null = null

export function setAuthProvider(next: AuthProvider | null): void {
    provider = next
}

export class ApiError extends Error {
    readonly status: number
    readonly code: string | undefined
    /** PostHog error `detail`, which is user-facing copy for most errors. */
    readonly detail: string | undefined
    readonly body: unknown
    readonly retryAfterSeconds: number | undefined

    constructor(status: number, body: unknown, headers?: Headers) {
        const record = isRecord(body) ? body : {}
        // Signals and tasks errors use `error` where DRF uses `detail`.
        const detail =
            typeof record.detail === 'string'
                ? record.detail
                : typeof record.error === 'string'
                  ? record.error
                  : undefined
        const code = typeof record.code === 'string' ? record.code : undefined
        super(detail ?? code ?? `Request failed with status ${status}`)
        this.name = 'ApiError'
        this.status = status
        this.code = code
        this.detail = detail
        this.body = body
        const retryAfter = headers?.get('Retry-After')
        this.retryAfterSeconds = retryAfter ? Number(retryAfter) || undefined : undefined
    }
}

export class NotSignedInError extends Error {
    constructor() {
        super('Sign in to continue')
        this.name = 'NotSignedInError'
    }
}

export type QueryValue = string | number | boolean | null | undefined

export interface ApiInit extends Omit<RequestInit, 'body' | 'headers'> {
    json?: unknown
    body?: RequestInit['body']
    headers?: Record<string, string>
    query?: Record<string, QueryValue>
    /** Spends this budget instead of the one the path belongs to. */
    budgetFamily?: BudgetFamily
}

function requireAuth(): ApiAuth {
    if (!provider) {
        throw new NotSignedInError()
    }
    const auth = provider.getAuth()
    if (!auth.host || !auth.accessToken) {
        throw new NotSignedInError()
    }
    return auth
}

export function projectPath(path: string): string {
    const auth = requireAuth()
    if (auth.projectId === null) {
        throw new Error('No project selected')
    }
    return `/api/projects/${auth.projectId}/${path.replace(/^\//, '')}`
}

export function buildQuery(query: Record<string, QueryValue> | undefined): string {
    if (!query) {
        return ''
    }
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
        if (value !== null && value !== undefined) {
            params.set(key, String(value))
        }
    }
    const encoded = params.toString()
    return encoded ? `?${encoded}` : ''
}

export function apiUrl(path: string, query?: Record<string, QueryValue>): string {
    const { host } = requireAuth()
    return `${host}${path.startsWith('/') ? path : `/${path}`}${buildQuery(query)}`
}

/** The web app URL of a page in the current project, or undefined when no session or project is set. */
export function projectWebUrl(path: string): string | undefined {
    try {
        return apiUrl(projectPath(path).replace(/^\/api\/projects\//, '/project/'))
    } catch {
        return undefined
    }
}

function buildInit(init: ApiInit, accessToken: string, accept: string): RequestInit {
    const { json, query: _query, budgetFamily: _budgetFamily, headers, ...rest } = init
    const merged: Record<string, string> = {
        Accept: accept,
        Authorization: `Bearer ${accessToken}`,
        // The tasks API reads this to skip warm-sandbox reuse and to label PRs opened from the app.
        'X-PostHog-Client-Platform': 'mobile',
        ...headers,
    }
    let body = rest.body
    if (json !== undefined) {
        merged['Content-Type'] = 'application/json'
        body = JSON.stringify(json)
    }
    return { ...rest, headers: merged, body }
}

type Fetcher = (url: string, init: RequestInit) => Promise<Response>

// Test doubles and some web responses have no `Date` header, or no headers at all.
function noteServerDate(response: Response): void {
    recordServerDate(response.headers?.get?.('Date'))
}

function isSameSession(a: ApiAuth, b: ApiAuth): boolean {
    return a.session === b.session && a.host === b.host
}

async function send(fetcher: Fetcher, path: string, init: ApiInit, accept: string): Promise<Response> {
    const auth = requireAuth()
    const url = apiUrl(path, init.query)
    const family = init.budgetFamily ?? budgetFamilyFor(path)
    if (family && !trySpend(family)) {
        throw new BudgetExceededError(family)
    }
    const sent = auth.accessToken as string
    let response = await fetcher(url, buildInit(init, sent, accept))
    noteServerDate(response)
    if (response.status === 401 && provider) {
        // The retry goes to `url`, which belongs to the session that sent the request. If the user signed out or
        // into another account while the request was in flight, the current token belongs to a different session,
        // and possibly to a different host. Sending it to `url` would give it to the earlier host.
        const current = provider.getAuth()
        if (!isSameSession(auth, current)) {
            throw new NotSignedInError()
        }
        // A refresh elsewhere may already have rotated the token this request used. Refreshing
        // again would revoke that newer token and 401 every other in-flight request.
        const token =
            current.accessToken && current.accessToken !== sent
                ? current.accessToken
                : await provider.refreshAccessToken()
        // The session can also change while the refresh is in flight.
        if (!token || !isSameSession(auth, provider.getAuth())) {
            throw new NotSignedInError()
        }
        response = await fetcher(url, buildInit(init, token, accept))
        noteServerDate(response)
    }
    return response
}

async function parseBody(response: Response): Promise<unknown> {
    const text = await response.text()
    if (!text) {
        return undefined
    }
    try {
        return JSON.parse(text) as unknown
    } catch {
        return text
    }
}

/** Sends a request and returns the raw response. Refreshes the token once on a 401. */
export async function apiFetch(path: string, init: ApiInit = {}): Promise<Response> {
    return withAppReloadBlocked(() => send((url, options) => fetch(url, options), path, init, 'application/json'))
}

export async function apiJson<T>(path: string, init: ApiInit = {}): Promise<T> {
    return withAppReloadBlocked(async () => {
        const response = await apiFetch(path, init)
        const body = await parseBody(response)
        if (!response.ok) {
            throw new ApiError(response.status, body, response.headers)
        }
        return body as T
    })
}

/** Uses expo's fetch, which exposes `response.body` as a readable stream on native. */
export async function apiStream(path: string, init: ApiInit = {}): Promise<Response> {
    const response = await send(
        (url, options) => streamingFetch(url, options as Parameters<typeof streamingFetch>[1]) as Promise<Response>,
        path,
        init,
        // JSON too, so content negotiation never answers 406 when the server replies in JSON, such as with an error.
        'text/event-stream, application/json'
    )
    if (!response.ok) {
        throw new ApiError(response.status, await parseBody(response), response.headers)
    }
    return response
}
