import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { http, HttpResponse, type JsonBodyType, type RequestHandler, type StrictRequest } from 'msw'

const FIXTURES_DIR = dirname(fileURLToPath(import.meta.url))

const fixture = (name: string): JsonBodyType =>
    JSON.parse(readFileSync(resolve(FIXTURES_DIR, name), 'utf-8')) as JsonBodyType

// Real PostHog API responses captured from a freshly-seeded local dev server
// (`./bin/start`) and sanitized — emails, distinct ids, project tokens, and
// org/team uuids replaced with stable test values.
const usersMe = fixture('api_users__me.json')
const personalApiKeyCurrent = fixture('api_personal_api_keys__current.json')
const project = fixture('api_projects_id.json')
const organization = fixture('api_organizations_id.json')
const groupTypes = fixture('api_projects_id_groups_types.json')

// `MCP.detectRegion` calls users/@me on both us.posthog.com and eu.posthog.com
// in parallel. Match any host with a leading `*` wildcard.
export const handlers: RequestHandler[] = [
    // OAuth introspection. MCP only falls back here when /personal_api_keys/@current
    // returns 401/403 — local dev rejects introspect for personal keys, so we
    // synthesize a healthy session-token response instead of capturing one.
    http.post('*/oauth/introspect', () =>
        HttpResponse.json({
            active: true,
            scope: '',
            scoped_teams: [],
            scoped_organizations: [],
        })
    ),
    http.get('*/api/users/@me', () => HttpResponse.json(usersMe)),
    http.get('*/api/users/@me/', () => HttpResponse.json(usersMe)),
    http.get('*/api/personal_api_keys/@current', () => HttpResponse.json(personalApiKeyCurrent)),
    http.get('*/api/personal_api_keys/@current/', () => HttpResponse.json(personalApiKeyCurrent)),
    http.get('*/api/organizations/:orgId', () => HttpResponse.json(organization)),
    http.get('*/api/organizations/:orgId/', () => HttpResponse.json(organization)),
    http.get('*/api/projects/:projectId/groups_types', () => HttpResponse.json(groupTypes)),
    http.get('*/api/projects/:projectId/groups_types/', () => HttpResponse.json(groupTypes)),
    http.get('*/api/projects/:projectId', () => HttpResponse.json(project)),
    http.get('*/api/projects/:projectId/', () => HttpResponse.json(project)),
]

/**
 * Dispatch a workerd outbound request to the matching MSW handler. Mirrors
 * MSW's internal handler-resolution loop without relying on global fetch
 * interception (which doesn't work inside the workerd runtime). The first
 * handler whose `run()` returns a response wins; everything else 404s.
 */
export async function dispatchHandlers(request: Request): Promise<Response> {
    // workerd's Request is structurally compatible with MSW's StrictRequest;
    // the cast just appeases the cf-properties shape mismatch.
    const msReq = request.clone() as unknown as StrictRequest<JsonBodyType>
    for (const handler of handlers) {
        // `run` is the same entrypoint MSW's setupServer uses internally.
        const result = await handler.run({ request: msReq, requestId: crypto.randomUUID() })
        if (result?.response) {
            return result.response
        }
    }
    return new Response(null, { status: 404 })
}
