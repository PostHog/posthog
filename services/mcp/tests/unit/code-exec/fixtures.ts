import type { ClassifierTable, FetchLike } from '@/lib/code-exec'

// A hand-written classifier table standing in for the generated artifact. It
// covers the operation shapes the golden scenarios exercise: numeric-id and
// string-id creates, update vs soft-delete on a shared PATCH path, reads, and
// the `POST /query/` read that must not be mistaken for a mutation.
export const FIXTURE_TABLE: ClassifierTable = {
    version: 1,
    operations: [
        {
            id: 'featureFlags.create',
            method: 'POST',
            pathTemplate: '/api/projects/{project_id}/feature_flags/',
            pathAliases: ['/api/environments/{project_id}/feature_flags/'],
            readOnly: false,
            destructive: false,
            softDelete: false,
            objectType: 'feature flag',
            displayNameFields: ['key', 'name'],
            scopes: ['feature_flag:write'],
            idFields: [{ name: 'id', type: 'number' }],
        },
        {
            id: 'featureFlags.update',
            method: 'PATCH',
            pathTemplate: '/api/projects/{project_id}/feature_flags/{id}/',
            pathAliases: ['/api/environments/{project_id}/feature_flags/{id}/'],
            readOnly: false,
            destructive: false,
            // Soft-delete-capable: a PATCH carrying `deleted:true` is a delete.
            softDelete: true,
            objectType: 'feature flag',
            displayNameFields: ['key', 'name'],
            scopes: ['feature_flag:write'],
            idFields: [{ name: 'id', type: 'number' }],
        },
        {
            id: 'featureFlags.list',
            method: 'GET',
            pathTemplate: '/api/projects/{project_id}/feature_flags/',
            pathAliases: [],
            readOnly: true,
            destructive: false,
            softDelete: false,
            objectType: 'feature flag',
            displayNameFields: ['key', 'name'],
            scopes: ['feature_flag:read'],
            idFields: [{ name: 'id', type: 'number' }],
        },
        {
            id: 'featureFlags.get',
            method: 'GET',
            pathTemplate: '/api/projects/{project_id}/feature_flags/{id}/',
            pathAliases: [],
            readOnly: true,
            destructive: false,
            softDelete: false,
            objectType: 'feature flag',
            displayNameFields: ['key', 'name'],
            scopes: ['feature_flag:read'],
            idFields: [{ name: 'id', type: 'number' }],
        },
        {
            id: 'annotations.create',
            method: 'POST',
            pathTemplate: '/api/projects/{project_id}/annotations/',
            pathAliases: [],
            readOnly: false,
            destructive: false,
            softDelete: false,
            objectType: 'annotation',
            displayNameFields: ['content'],
            scopes: ['annotation:write'],
            idFields: [{ name: 'id', type: 'number' }],
        },
        {
            id: 'surveys.create',
            method: 'POST',
            pathTemplate: '/api/projects/{project_id}/surveys/',
            pathAliases: [],
            readOnly: false,
            destructive: false,
            softDelete: false,
            objectType: 'survey',
            displayNameFields: ['name'],
            scopes: ['survey:write'],
            idFields: [{ name: 'id', type: 'string' }],
        },
        {
            id: 'query.run',
            method: 'POST',
            pathTemplate: '/api/environments/{project_id}/query/',
            pathAliases: ['/api/projects/{project_id}/query/'],
            readOnly: true,
            destructive: false,
            softDelete: false,
            objectType: 'query',
            displayNameFields: [],
            scopes: ['query:read'],
            idFields: [],
        },
    ],
}

/** A `fetch` that fails the test if it is ever called — the plan pass must never forward. */
export const failingFetch: FetchLike = () => {
    throw new Error('realFetch must not be called during the plan pass')
}

/** Build a `fetch` stub returning canned JSON responses keyed by `METHOD path`. */
export function stubFetch(responses: Record<string, { status?: number; body: unknown }>): {
    fetch: FetchLike
    calls: Array<{ method: string; url: string; body: unknown }>
} {
    const calls: Array<{ method: string; url: string; body: unknown }> = []
    const fetch: FetchLike = async (input, init) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
        const method = (init?.method ?? 'GET').toUpperCase()
        const path = new URL(url, 'http://placeholder').pathname
        const rawBody = typeof init?.body === 'string' ? init.body : null
        calls.push({ method, url, body: rawBody === null ? undefined : JSON.parse(rawBody) })
        const canned = responses[`${method} ${path}`]
        if (!canned) {
            return new Response('null', { status: 200, headers: { 'content-type': 'application/json' } })
        }
        return new Response(JSON.stringify(canned.body), {
            status: canned.status ?? 200,
            headers: { 'content-type': 'application/json' },
        })
    }
    return { fetch, calls }
}

/** JSON body helper for building fetch RequestInit. */
export function jsonInit(method: string, body?: unknown): RequestInit {
    return {
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
        headers: { 'content-type': 'application/json' },
    }
}
