import { fetch as streamingFetch } from 'expo/fetch'

import { abortError } from '@/lib/abort'
import { withAppReloadBlocked } from '@/lib/appReload'
import { isRecord } from '@/lib/records'

import { BudgetExceededError, type BudgetFamily, budgetFamilyFor, trySpend } from './budget'
import type { ProjectScope } from './reports'
import { recordServerDate } from './serverClock'
import { requestWithDeadline, transport } from './transport'

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

/** The request belongs to a session that left memory before its result arrived, so no caller may use the result. */
export class SessionEndedError extends NotSignedInError {
    constructor() {
        super()
        this.message = 'The account changed before this request finished.'
        this.name = 'SessionEndedError'
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

function hostKey(host: string): string {
    return host.replace(/\/+$/, '').toLowerCase()
}

// The session's token works only on its own host, so a scope on another host throws.
export function scopedPath(scope: ProjectScope | null, path: string): string {
    const auth = requireAuth()
    if (scope === null) {
        throw new NotSignedInError()
    }
    if (hostKey(scope.host) !== hostKey(auth.host)) {
        throw new Error('This project is in another region')
    }
    return `/api/projects/${scope.projectId}/${path.replace(/^\//, '')}`
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

function urlFor(host: string, path: string, query?: Record<string, QueryValue>): string {
    return `${host}${path.startsWith('/') ? path : `/${path}`}${buildQuery(query)}`
}

export function apiUrl(path: string, query?: Record<string, QueryValue>): string {
    return urlFor(requireAuth().host, path, query)
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

interface SessionRequests {
    session: number
    controller: AbortController
    pending: Set<Promise<unknown>>
}

let sessionRequests: SessionRequests | null = null
/** The latest session whose requests ended. Every request of it or of an earlier session fails at once. */
let endedSession = Number.NEGATIVE_INFINITY

function requestsOf(session: number): SessionRequests {
    if (sessionRequests?.session !== session) {
        sessionRequests?.controller.abort()
        sessionRequests = { session, controller: new AbortController(), pending: new Set() }
    }
    return sessionRequests
}

function isCurrent(auth: ApiAuth): boolean {
    return auth.session > endedSession && provider !== null && isSameSession(auth, provider.getAuth())
}

/** Starts a request of `auth`'s session. Its promise rejects with `SessionEndedError` once that session ends. */
function sessionRequest<T>(auth: ApiAuth, work: (signal: AbortSignal) => Promise<T>): Promise<T> {
    if (auth.session <= endedSession) {
        return Promise.reject(new SessionEndedError())
    }
    const requests = requestsOf(auth.session)
    const promise = work(requests.controller.signal).then(
        (value) => {
            if (!isCurrent(auth)) {
                throw new SessionEndedError()
            }
            return value
        },
        (error: unknown) => {
            throw isCurrent(auth) ? error : new SessionEndedError()
        }
    )
    requests.pending.add(promise)
    const settle = (): void => {
        requests.pending.delete(promise)
    }
    promise.then(settle, settle)
    return promise
}

/**
 * Ends every request of the session that is leaving memory, before a switch, sign out or expiry starts the next one.
 * Resolves after the callers of those requests ran their continuations, so a rollback, cache write or analytics event
 * of the earlier session lands before its caches and analytics reset, never in the next session's.
 */
export async function endSessionRequests(): Promise<void> {
    if (!provider) {
        return
    }
    const { session } = provider.getAuth()
    endedSession = Math.max(endedSession, session)
    const requests = sessionRequests?.session === session ? sessionRequests : null
    if (!requests) {
        return
    }
    requests.controller.abort()
    await Promise.allSettled([...requests.pending])
    // Continuations run as microtasks, and a macrotask starts only after every queued microtask ran.
    await new Promise<void>((resolve) => setTimeout(resolve, 0))
}

function linkSignals(
    caller: AbortSignal | null | undefined,
    session: AbortSignal
): { signal: AbortSignal; release: () => void } {
    if (!caller) {
        return { signal: session, release: () => undefined }
    }
    const controller = new AbortController()
    const abort = (): void => controller.abort()
    if (caller.aborted || session.aborted) {
        controller.abort()
    }
    caller.addEventListener('abort', abort, { once: true })
    session.addEventListener('abort', abort, { once: true })
    return {
        signal: controller.signal,
        release: () => {
            caller.removeEventListener('abort', abort)
            session.removeEventListener('abort', abort)
        },
    }
}

/** The URL and token of the request the server answered, so a reader can pair them without reading the session again. */
export interface SentRequest {
    url: string
    accessToken: string
}

async function send(
    fetcher: Fetcher,
    auth: ApiAuth,
    path: string,
    init: ApiInit,
    accept: string
): Promise<{ response: Response; sent: SentRequest }> {
    const url = urlFor(auth.host, path, init.query)
    const family = init.budgetFamily ?? budgetFamilyFor(path)
    if (family && !trySpend(family)) {
        throw new BudgetExceededError(family)
    }
    let token = auth.accessToken as string
    const fetchResponse = (bearer: string): Promise<Response> => {
        if (init.signal?.aborted) {
            throw abortError()
        }
        const options = buildInit(init, bearer, accept)
        return transport(() => fetcher(url, options))
    }
    let response = await fetchResponse(token)
    if (init.signal?.aborted) {
        throw abortError()
    }
    noteServerDate(response)
    if (response.status === 401 && provider) {
        // The retry goes to `url`, which belongs to the session that sent the request. If the user signed out or
        // into another account while the request was in flight, the current token belongs to a different session,
        // and possibly to a different host. Sending it to `url` would give it to the earlier host.
        const current = provider.getAuth()
        if (!isSameSession(auth, current)) {
            throw new SessionEndedError()
        }
        // A refresh elsewhere may already have rotated the token this request used. Refreshing
        // again would revoke that newer token and 401 every other in-flight request.
        const next =
            current.accessToken && current.accessToken !== token
                ? current.accessToken
                : await provider.refreshAccessToken()
        if (!isCurrent(auth)) {
            throw new SessionEndedError()
        }
        if (!next) {
            throw new NotSignedInError()
        }
        token = next
        response = await fetchResponse(token)
        noteServerDate(response)
    }
    return { response, sent: { url, accessToken: token } }
}

async function parseBody(response: Response): Promise<unknown> {
    const text = await transport(() => response.text())
    if (!text) {
        return undefined
    }
    try {
        return JSON.parse(text) as unknown
    } catch {
        return text
    }
}

export async function apiReadResponse<T>(
    path: string,
    init: ApiInit,
    read: (response: Response, sent: SentRequest) => Promise<T>
): Promise<T> {
    const auth = requireAuth()
    return sessionRequest(auth, async (sessionSignal) => {
        const { signal, release } = linkSignals(init.signal, sessionSignal)
        try {
            return await withAppReloadBlocked(() =>
                requestWithDeadline(async (deadline) => {
                    const { response, sent } = await send(
                        (url, options) => fetch(url, options),
                        auth,
                        path,
                        { ...init, signal: deadline },
                        'application/json'
                    )
                    if (deadline.aborted) {
                        throw abortError()
                    }
                    return read(response, sent)
                }, signal)
            )
        } finally {
            release()
        }
    })
}

export async function apiJson<T>(path: string, init: ApiInit = {}): Promise<T> {
    return apiReadResponse(path, init, async (response) => {
        const body = await parseBody(response)
        if (!response.ok) {
            throw new ApiError(response.status, body, response.headers)
        }
        return body as T
    })
}

/**
 * Uses expo's fetch, which exposes `response.body` as a readable stream on native. The stream ends when its session
 * ends, because the session's signal aborts the fetch.
 */
export async function apiStream(path: string, init: ApiInit = {}): Promise<Response> {
    const auth = requireAuth()
    return sessionRequest(auth, async (sessionSignal) => {
        const { signal } = linkSignals(init.signal, sessionSignal)
        const ended = new Promise<never>((_resolve, reject) => {
            const fail = (): void => reject(abortError())
            if (signal.aborted) {
                fail()
            }
            signal.addEventListener('abort', fail, { once: true })
        })
        ended.catch(() => undefined)
        const { response } = await Promise.race([
            send(
                (url, options) =>
                    streamingFetch(url, options as Parameters<typeof streamingFetch>[1]) as Promise<Response>,
                auth,
                path,
                { ...init, signal },
                // JSON too, so content negotiation never answers 406 when the server replies in JSON, such as with an error.
                'text/event-stream, application/json'
            ),
            ended,
        ])
        if (!response.ok) {
            throw new ApiError(response.status, await parseBody(response), response.headers)
        }
        return response
    })
}
