// Talking to PostHog. Three calls: resolve the key, create, update.

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { WorkflowError } from '../errors.js'
import type { Credentials } from './credentials.js'

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

function describeFailure(status: number, body: string): { status: string; message: string; why: string; fix: string } {
    let detail = body.slice(0, 500)
    try {
        const parsed = JSON.parse(body) as { detail?: string; extra?: { fix?: string } }
        detail = parsed.detail ?? detail
        if (parsed.extra?.fix !== undefined) {
            return {
                status: `http_${status}`,
                message: 'PostHog refused the write.',
                why: detail,
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
            fix: 'Give the personal API key the hog_flow:write scope for this project.',
        }
    }
    if (status === 400) {
        return {
            status: 'http_400',
            message: 'PostHog refused the workflow definition.',
            why: detail,
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

    urlFor(id: string): string {
        return `${this.credentials.host}/project/${this.credentials.projectId}/workflows/${id}`
    }

    private get base(): string {
        return `/api/environments/${this.credentials.projectId}/hog_flows/`
    }

    private async request(method: string, path: string, body?: unknown): Promise<StoredWorkflow> {
        let response: Response
        try {
            response = await fetch(`${this.credentials.host}${path}`, {
                method,
                headers: {
                    Authorization: `Bearer ${this.credentials.apiKey}`,
                    'Content-Type': 'application/json',
                    'User-Agent': userAgent(),
                },
                ...(body === undefined ? {} : { body: JSON.stringify(body) }),
            })
        } catch (error) {
            throw new WorkflowError({
                status: 'network_error',
                message: `Could not reach ${this.credentials.host}.`,
                why: error instanceof Error ? error.message : String(error),
                fix: 'Check that the host is reachable from here, then run the command again.',
            })
        }
        if (!response.ok) {
            throw new WorkflowError(describeFailure(response.status, await response.text()))
        }
        return (await response.json()) as StoredWorkflow
    }

    /**
     * The workflow this key owns, or null when the project has none.
     *
     * A row is a match only when it carries the key. A PostHog that does not know the filter
     * answers with the first page of every workflow in the project instead, and adopting a row
     * out of that would overwrite a workflow nobody meant to touch.
     */
    async resolve(key: string): Promise<StoredWorkflow | null> {
        const page = (await this.request('GET', `${this.base}?key=${encodeURIComponent(key)}`)) as unknown as {
            results?: StoredWorkflow[]
        }
        const rows = page.results ?? []
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
        return await this.request('POST', this.base, body)
    }

    async update(id: string, body: Readonly<Record<string, unknown>>): Promise<StoredWorkflow> {
        return await this.request('PATCH', `${this.base}${id}/`, body)
    }
}
