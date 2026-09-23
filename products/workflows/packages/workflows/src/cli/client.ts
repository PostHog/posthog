// Talking to PostHog. Three calls: resolve the key, create, update.

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { WorkflowError } from '../errors.js'
import type { Credentials } from './credentials.js'

const REQUEST_TIMEOUT_MS = 30_000

export interface StoredWorkflow extends Record<string, unknown> {
    readonly id: string
    readonly version?: number
}

/**
 * The user agent classifies the push as the event source `api`, which the write guard allows.
 * It deliberately is not `posthog-cli`: that string maps to the event source `cli`, which the
 * revision history would label MCP.
 */
export function userAgent(): string {
    return `posthog-workflows/${packageVersion()}`
}

function packageVersion(): string {
    // The built CLI and the test build sit at different depths under the package, so find the
    // manifest rather than counting directories.
    let directory = dirname(fileURLToPath(import.meta.url))
    for (let level = 0; level < 6; level += 1) {
        try {
            const manifest = JSON.parse(readFileSync(join(directory, 'package.json'), 'utf8')) as {
                name?: string
                version?: string
            }
            if (manifest.name === '@posthog/workflows' && manifest.version !== undefined) {
                return manifest.version
            }
        } catch {
            // Keep walking up.
        }
        directory = dirname(directory)
    }
    return '0.0.0'
}

function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function invalidResponse(method: string, path: string, why: string): WorkflowError {
    const writeWarning =
        method === 'POST' || method === 'PATCH' ? ` The ${method} to ${path} may already have changed PostHog.` : ''
    return new WorkflowError({
        status: 'invalid_response',
        message: 'PostHog returned a response the CLI could not read.',
        why: `${why}${writeWarning}`,
        fix:
            method === 'POST' || method === 'PATCH'
                ? 'Check the workflow in PostHog before you run the command again.'
                : 'Run the command again. If it keeps happening, check that the host is a compatible PostHog.',
    })
}

function storedWorkflow(method: string, path: string, value: unknown): StoredWorkflow {
    if (isObject(value) && typeof value.id === 'string') {
        return value as StoredWorkflow
    }
    throw invalidResponse(method, path, 'The response body did not include a workflow id.')
}

function describeRedirect(
    method: string,
    path: string,
    status: number,
    location: string | null
): { status: string; message: string; why: string; fix: string } {
    return {
        status: 'redirect',
        message: 'PostHog redirected the request.',
        why: `The ${method} to ${path} returned ${status}${location === null ? '' : ` to ${location}`}. The CLI will not follow redirects with an API key.`,
        fix: 'Set --host to the final PostHog URL, then run the command again.',
    }
}

function describeFailure(status: number, body: string): { status: string; message: string; why: string; fix: string } {
    let detail = body.slice(0, 500)
    let attr: string | undefined
    try {
        const parsed = JSON.parse(body) as { attr?: string; detail?: string; extra?: { fix?: string } }
        detail = parsed.detail ?? detail
        attr = parsed.attr
        if (parsed.extra?.fix !== undefined) {
            return {
                status: `http_${status}`,
                message: 'PostHog refused the write.',
                why: attr === undefined ? detail : `${attr}: ${detail}`,
                fix: parsed.extra.fix,
            }
        }
    } catch {
        // Not JSON. The raw body is still the most useful thing to show.
    }
    if (status === 401) {
        return {
            status: 'http_401',
            message: 'PostHog did not accept the API key.',
            why: detail,
            fix: 'Check the key is current, and that the host is the same PostHog that issued it.',
        }
    }
    if (status === 403) {
        return {
            status: 'http_403',
            message: 'The API key may not write workflows in this project.',
            why: detail,
            fix: 'Give the API key the hog_flow:write scope for this project.',
        }
    }
    if (status === 400) {
        return {
            status: 'http_400',
            message: 'PostHog refused the workflow definition.',
            why: attr === undefined ? detail : `${attr}: ${detail}`,
            fix: 'Fix the step the message names. PostHog validates templates and inputs that check does not.',
        }
    }
    return {
        status: `http_${status}`,
        message: `PostHog returned ${status}.`,
        why: detail,
        fix: 'Run the command again. If it keeps happening, run check and compare what it prints against the workflow in PostHog.',
    }
}

export class Client {
    constructor(private readonly credentials: Credentials) {}

    get host(): string {
        return this.credentials.host
    }

    /**
     * The workflow itself. Without the last segment this is the list of every workflow.
     *
     * @param id - The id PostHog gave the stored workflow.
     */
    urlFor(id: string): string {
        return `${this.credentials.host}/project/${this.credentials.projectId}/workflows/${id}/workflow`
    }

    private get base(): string {
        return `/api/environments/${this.credentials.projectId}/hog_flows/`
    }

    private async request(method: string, path: string, body?: unknown): Promise<unknown> {
        try {
            const response = await fetch(`${this.credentials.host}${path}`, {
                method,
                headers: {
                    Authorization: `Bearer ${this.credentials.apiKey}`,
                    'Content-Type': 'application/json',
                    'User-Agent': userAgent(),
                },
                ...(body === undefined ? {} : { body: JSON.stringify(body) }),
                redirect: 'manual',
                // A host that accepts the connection and never answers would otherwise hold a
                // CI job until the runner's own timeout kills it, with no line saying why.
                signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
            })
            // The signal also governs the body read, so it stays inside the try.
            const text = await response.text()
            if (response.status >= 300 && response.status < 400) {
                throw new WorkflowError(
                    describeRedirect(method, path, response.status, response.headers.get('location'))
                )
            }
            if (!response.ok) {
                throw new WorkflowError(describeFailure(response.status, text))
            }
            try {
                return JSON.parse(text) as unknown
            } catch {
                throw invalidResponse(method, path, 'The response body was not valid JSON.')
            }
        } catch (error) {
            if (error instanceof WorkflowError) {
                throw error
            }
            if (error instanceof Error && error.name === 'TimeoutError') {
                throw new WorkflowError({
                    status: 'timeout',
                    message: `${this.credentials.host} did not answer within ${REQUEST_TIMEOUT_MS / 1000} seconds.`,
                    why: `The ${method} to ${path} was sent and no response came back in time.`,
                    fix: 'Check that the host is the right PostHog and that it is up, then run the command again.',
                })
            }
            throw new WorkflowError({
                status: 'network_error',
                message: `Could not reach ${this.credentials.host}.`,
                why: error instanceof Error ? error.message : String(error),
                fix: 'Check that the host is reachable from here, then run the command again.',
            })
        }
    }

    /**
     * The workflow this key owns, or null when the project has none.
     *
     * A row is a match only when it carries the key. A PostHog that does not know the filter
     * answers with the first page of every workflow in the project instead, and adopting a row
     * out of that would overwrite a workflow nobody meant to touch.
     *
     * @param key - The key the workflow file declares, which is the identity PostHog matches on.
     */
    async resolve(key: string): Promise<StoredWorkflow | null> {
        const path = `${this.base}?key=${encodeURIComponent(key)}`
        const page = await this.request('GET', path)
        if (!isObject(page) || !Array.isArray(page.results)) {
            throw invalidResponse('GET', path, 'The list response did not include a results array.')
        }
        const rows = page.results as StoredWorkflow[]
        // A row that carries no key at all means this PostHog does not know the field, so the
        // filter was ignored and nothing here can be resolved. Creating would add a second live
        // workflow on every run, silently, which is worse than stopping.
        if (rows.length > 0 && rows.every((row) => row.key === undefined)) {
            throw new WorkflowError({
                status: 'key_not_supported',
                message: 'This PostHog does not store a workflow key yet.',
                why: 'The list came back with workflows that carry no key, so the key filter was ignored. Without it a push cannot tell which workflow the file owns, and every run would create another one.',
                fix: 'Push to a PostHog that supports the workflow key. On PostHog Cloud this is already the case; a self-hosted instance needs the version that added it.',
            })
        }
        const matches = rows.filter((row) => row.key === key)
        if (matches.length > 1) {
            throw new WorkflowError({
                status: 'ambiguous_key',
                message: `This project holds ${matches.length} workflows with the key "${key}".`,
                why: 'A key identifies one workflow in a project, and the CLI will not choose between rows that claim the same one.',
                fix: `Delete or re-key the extra workflows in PostHog so one row carries "${key}".`,
            })
        }
        return matches[0] ?? null
    }

    async create(body: Readonly<Record<string, unknown>>): Promise<StoredWorkflow> {
        return storedWorkflow('POST', this.base, await this.request('POST', this.base, body))
    }

    async update(id: string, body: Readonly<Record<string, unknown>>): Promise<StoredWorkflow> {
        const path = `${this.base}${id}/`
        return storedWorkflow('PATCH', path, await this.request('PATCH', path, body))
    }
}
