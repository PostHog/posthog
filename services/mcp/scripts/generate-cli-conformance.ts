#!/usr/bin/env tsx
/**
 * Generates wire-level conformance expected requests for the agent CLI.
 *
 * Drives the REAL generated MCP tool handlers for a corpus of (tool, params) cases,
 * capturing the exact request each handler builds (`context.api.request(...)`). The
 * Rust interpreter's conformance test then asserts it produces the identical request
 * from the same params + the generated manifest — making "the CLI does not change
 * tool behavior" a verifiable invariant against the MCP's own handler code.
 *
 * Scope: REST tools. The handlers build the full request themselves, so a mock
 * `api.request` captures it faithfully without importing `client.ts` (which depends
 * on the Cloudflare Workers runtime and can't load under tsx). Query-wrapper/actors
 * request shaping lives in `client.ts` (normalizeQuery / runActorsQuery) and is
 * covered by the Rust code-derived tests + `tests/unit/query-wrapper-factory.test.ts`;
 * an end-to-end live capture for those requires the workers vitest pool (follow-up).
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

import { GENERATED_TOOL_MAP } from '../src/tools/generated'

const PROJECT_ID = '2'
const BASE_URL = 'http://localhost:8010'
const OUT_PATH = path.resolve(__dirname, '..', 'schema', 'cli-conformance-expected-requests.json')

class CaptureSignal extends Error {
    constructor(public readonly request: CapturedRequest) {
        super('captured')
    }
}

interface CapturedRequest {
    method: string
    path: string
    body?: Record<string, unknown>
    query?: Record<string, unknown>
}

interface CorpusCase {
    tool: string
    params: Record<string, unknown>
}

// REST tools spanning every request-shaping transform: body whitelist, soft-delete,
// query + casts, path + cast, path + body, rename_params, inject_body.
const CORPUS: CorpusCase[] = [
    { tool: 'create-feature-flag', params: { key: 'my-flag', name: 'My Flag', active: true } },
    { tool: 'delete-feature-flag', params: { id: '123' } },
    { tool: 'feature-flag-get-all', params: { search: 'foo', limit: '10' } },
    { tool: 'feature-flag-get-definition', params: { id: '456' } },
    { tool: 'update-feature-flag', params: { id: '1', name: 'New' } },
    // Exercises param defaults: external-data-sources-create applies the OpenAPI body default
    // access_method: 'warehouse' + inject_body created_via: 'mcp'; activity-log-list applies the
    // param_overrides default page_size: 10.
    { tool: 'external-data-sources-create', params: { source_type: 'Stripe', payload: {} } },
    { tool: 'activity-log-list', params: {} },
]

/** Mirror of the query serialization in services/mcp/src/api/client.ts (skip null/empty-array, JSON-stringify objects). */
function toWireQuery(query: Record<string, unknown> | undefined): Record<string, string> {
    const out: Record<string, string> = {}
    if (!query) {
        return out
    }
    for (const [k, v] of Object.entries(query)) {
        if (v === undefined || v === null) {
            continue
        }
        if (Array.isArray(v) && v.length === 0) {
            continue
        }
        out[k] = typeof v === 'object' ? JSON.stringify(v) : String(v)
    }
    return out
}

async function main(): Promise<void> {
    const context = {
        api: {
            request: async (opts: CapturedRequest) => {
                throw new CaptureSignal(opts)
            },
            getProjectBaseUrl: (pid: string) => `${BASE_URL}/project/${pid}`,
        },
        stateManager: {
            getProjectId: async () => PROJECT_ID,
            getOrgID: async () => 'org-1',
        },
    } as unknown as Parameters<ReturnType<(typeof GENERATED_TOOL_MAP)[string]>['handler']>[0]

    const expectedRequests: Record<string, unknown> = {}
    const skipped: string[] = []

    for (const { tool: name, params } of CORPUS) {
        const factory = GENERATED_TOOL_MAP[name]
        if (!factory) {
            skipped.push(`${name} (not in tool map)`)
            continue
        }
        const tool = factory()
        try {
            // Mirror the framework: parse params through the tool schema (applies casts), then run the handler.
            const parsed = tool.schema ? tool.schema.parse(params) : params
            // eslint-disable-next-line no-await-in-loop
            await tool.handler(context, parsed as never)
            skipped.push(`${name} (no request captured)`)
        } catch (err) {
            if (!(err instanceof CaptureSignal)) {
                skipped.push(`${name} (${(err as Error).message.split('\n')[0]})`)
                continue
            }
            const c = err.request
            expectedRequests[name] = {
                params,
                request: {
                    method: c.method,
                    path: c.path,
                    query: toWireQuery(c.query),
                    body: c.body ?? null,
                },
            }
        }
    }

    fs.writeFileSync(OUT_PATH, JSON.stringify(expectedRequests, null, 2) + '\n')
    process.stdout.write(
        `Wrote ${Object.keys(expectedRequests).length} conformance expected request(s) to ${path.relative(process.cwd(), OUT_PATH)}\n`
    )
    if (skipped.length > 0) {
        process.stdout.write(`Skipped ${skipped.length}: ${skipped.join('; ')}\n`)
    }
}

void main()
