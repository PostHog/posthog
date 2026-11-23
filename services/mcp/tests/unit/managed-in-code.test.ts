import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createApiToolLibrary } from '@/cli/library'
import { handleToolError, PostHogApiError } from '@/lib/errors'
import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { CREATE_TOOLS_BY_KIND, createRedirectMessage, writeRefusedMessage } from '@/tools/managed-in-code'
import { mergeToolFactories } from '@/tools/mergeToolFactories'
import type { Context } from '@/tools/types'

const PROJECT = '42'
const MANAGED_KINDS_PATH = `/api/projects/${PROJECT}/stacks/managed_kinds/`
const ENDPOINTS_PATH = `/api/projects/${PROJECT}/endpoints/`
const CONNECTION = {
    apiKey: 'phx_test',
    host: 'https://app.example.com',
    projectId: PROJECT,
    clientName: 'hog',
    clientVersion: '0.0.0',
}

const ENDPOINT_ROW = {
    kind: 'endpoint',
    stack_name: 'web-app',
    repository: 'acme/web-app',
    definitions: 3,
    redirect_creates: true,
}

const REFUSAL = {
    type: 'invalid_request',
    code: 'managed_in_code',
    detail: 'This endpoint is managed in code by the stack web-app in acme/web-app, so it cannot be changed here.',
    attr: null,
    extra: {
        stack: 'web-app',
        repository: 'acme/web-app',
        source: { file: '.ph/endpoints.ts', export: 'revenue' },
        fields: ['description', 'query'],
    },
}

type ManagedKindsAnswer = Response | (() => Response)

interface FakePostHog {
    fetch: typeof globalThis.fetch
    requests: { method: string; path: string }[]
}

function fakePostHog(managedKinds: ManagedKindsAnswer): FakePostHog {
    const requests: { method: string; path: string }[] = []
    const fetch = async (url: string | URL | Request, init: RequestInit = {}): Promise<Response> => {
        const path = new URL(String(url)).pathname
        const method = (init.method ?? 'GET').toUpperCase()
        requests.push({ method, path })
        if (path === MANAGED_KINDS_PATH) {
            return typeof managedKinds === 'function' ? managedKinds() : managedKinds.clone()
        }
        if (path === ENDPOINTS_PATH && method === 'POST') {
            return Response.json({ name: 'revenue' }, { status: 201 })
        }
        if (path === `${ENDPOINTS_PATH}revenue/` && method === 'PATCH') {
            return Response.json(REFUSAL, { status: 409 })
        }
        return Response.json({ id: 1, organization: 'org', scopes: ['*'], scoped_teams: [], scoped_organizations: [] })
    }
    return { fetch: fetch as typeof globalThis.fetch, requests }
}

const createEndpoint = (fake: FakePostHog): ReturnType<ReturnType<typeof createApiToolLibrary>['call']> =>
    createApiToolLibrary({ fetch: fake.fetch }).call('endpoint-create', { name: 'revenue' }, CONNECTION, false)

const createRequests = (fake: FakePostHog): number =>
    fake.requests.filter((request) => request.method === 'POST' && request.path === ENDPOINTS_PATH).length

const lookups = (fake: FakePostHog): number =>
    fake.requests.filter((request) => request.path === MANAGED_KINDS_PATH).length

const BANNED_WORDS = /\b(terraform|opentofu|tofu|providers?|state|plans?|apply|hcl|resource address)\b/i

describe('managed in code', () => {
    describe('a create tool for a kind a stack keeps in code', () => {
        it.each([
            ['event', 'event-definition-create', { eventName: 'signup' }],
            ['property_group', 'schema-property-group-create', { name: 'signup' }],
            ['flag', 'create-feature-flag', { key: 'beta', name: 'Beta' }],
            ['model', 'view-create', { name: 'revenue', query: { kind: 'HogQLQuery', query: 'select 1' } }],
            ['endpoint', 'endpoint-create', { name: 'revenue' }],
            ['metric', 'data-catalog-metric-create', { name: 'mrr', description: 'Monthly revenue' }],
        ])(
            'answers a %s create with the stack and the steps, and sends nothing but reads',
            async (kind, tool, input) => {
                const fake = fakePostHog(Response.json({ results: [{ ...ENDPOINT_ROW, kind }] }))

                const result = await createApiToolLibrary({ fetch: fake.fetch }).call(tool, input, CONNECTION, false)

                expect(fake.requests.filter((request) => request.method !== 'GET')).toEqual([])
                expect(result).toMatchObject({
                    ok: false,
                    error: {
                        code: 'managed_in_code',
                        managedInCode: {
                            reason: 'create_redirected',
                            kind,
                            stacks: [{ name: 'web-app', repository: 'acme/web-app' }],
                        },
                    },
                })
                const message = result.ok ? '' : result.error.message
                expect(message).toMatch(/^Nothing was created\./)
                expect(message).toContain('the stack web-app in the repository acme/web-app')
                expect(message).toContain('`hog check`')
                expect(message).toContain('pull request')
            }
        )

        it.each([
            ['no stack manages anything', () => Response.json({ results: [] })],
            ['a stack manages only other kinds', () => Response.json({ results: [{ ...ENDPOINT_ROW, kind: 'flag' }] })],
            [
                'the kind is managed but creates are not redirected',
                () => Response.json({ results: [{ ...ENDPOINT_ROW, redirect_creates: false }] }),
            ],
            ['the instance has no stacks API', () => Response.json({ detail: 'Not found.' }, { status: 404 })],
            ['the lookup fails', () => new Response('upstream failed', { status: 500 })],
            ['the lookup answers something unexpected', () => Response.json({ results: 'nope' })],
        ])('creates as before when %s', async (_name, managedKinds) => {
            const fake = fakePostHog(managedKinds)

            const result = await createEndpoint(fake)

            expect(result).toMatchObject({ ok: true })
            expect(createRequests(fake)).toBe(1)
        })

        it('creates without a lookup when the key cannot read stacks', async () => {
            const fake = fakePostHog(Response.json({ results: [ENDPOINT_ROW] }))
            const fetch = fake.fetch
            fake.fetch = (async (url: string | URL | Request, init?: RequestInit) =>
                new URL(String(url)).pathname === '/api/personal_api_keys/@current'
                    ? Response.json({ id: 1, organization: 'org', scopes: ['endpoint:write'], scoped_teams: [] })
                    : fetch(url, init)) as typeof globalThis.fetch

            const result = await createEndpoint(fake)

            expect(result).toMatchObject({ ok: true })
            expect(lookups(fake)).toBe(0)
        })
    })

    describe('the lookup cache', () => {
        beforeEach(() => {
            vi.useFakeTimers({ toFake: ['Date'] })
            vi.setSystemTime(new Date('2026-11-21T10:00:00Z'))
        })

        afterEach(() => {
            vi.useRealTimers()
        })

        it('asks once per project and asks again after a minute', async () => {
            const fake = fakePostHog(Response.json({ results: [] }))
            const library = createApiToolLibrary({ fetch: fake.fetch })
            const create = (): ReturnType<typeof library.call> =>
                library.call('endpoint-create', { name: 'revenue' }, CONNECTION, false)

            await create()
            await create()
            expect(lookups(fake)).toBe(1)

            vi.setSystemTime(new Date('2026-11-21T10:01:01Z'))
            await create()
            expect(lookups(fake)).toBe(2)
            expect(createRequests(fake)).toBe(3)
        })
    })

    describe('a write the API refuses because a stack manages the entity', () => {
        it('names the stack, the file and export, and the fields code owns', async () => {
            const fake = fakePostHog(Response.json({ results: [] }))

            const result = await createApiToolLibrary({ fetch: fake.fetch }).call(
                'endpoint-update',
                { name: 'revenue', description: 'Renamed' },
                CONNECTION,
                false
            )

            expect(result).toMatchObject({
                ok: false,
                error: {
                    code: 'managed_in_code',
                    managedInCode: {
                        reason: 'write_refused',
                        stacks: [{ name: 'web-app', repository: 'acme/web-app' }],
                        source: { file: '.ph/endpoints.ts', export: 'revenue' },
                        fields: ['description', 'query'],
                    },
                },
            })
            const message = result.ok ? '' : result.error.message
            expect(message).toContain('the export revenue in .ph/endpoints.ts')
            expect(message).toContain('Code owns these fields: description, query.')
            expect(message).toContain('Fields code does not own can still be changed')
        })

        it('reaches the agent on the hosted server as a recoverable error with the same text', async () => {
            const tool = mergeToolFactories({ generated: GENERATED_TOOL_MAP, handwritten: TOOL_MAP })[
                'endpoint-update'
            ]!()
            const refusal = new PostHogApiError({
                status: 409,
                statusText: 'Conflict',
                body: JSON.stringify(REFUSAL),
                url: `https://app.example.com${ENDPOINTS_PATH}revenue/`,
                method: 'PATCH',
            })
            const context = {
                stateManager: { getProjectId: async () => PROJECT },
                api: { request: async () => Promise.reject(refusal) },
            } as unknown as Context

            const error = await tool
                .handler(context, { name: 'revenue', description: 'Renamed' })
                .catch((caught) => caught)
            const answer = handleToolError(error, 'endpoint-update')

            expect(answer.isError).toBe(true)
            expect(answer.content[0]).toMatchObject({
                type: 'text',
                text: expect.stringContaining('Its definition is the export revenue in .ph/endpoints.ts.'),
            })
        })
    })

    it('keeps both answers to the words a person sees', () => {
        const texts = [
            createRedirectMessage('endpoint', [ENDPOINT_ROW]),
            createRedirectMessage('flag', [ENDPOINT_ROW, { ...ENDPOINT_ROW, stack_name: 'api', repository: null }]),
            writeRefusedMessage({
                reason: 'write_refused',
                stacks: [{ name: 'web-app', repository: 'acme/web-app' }],
                source: { file: '.ph/flags.ts', export: 'beta' },
                fields: ['name'],
            }),
            writeRefusedMessage({ reason: 'write_refused', stacks: [] }),
        ]

        for (const text of texts) {
            expect(text).not.toMatch(BANNED_WORDS)
            expect(text).not.toMatch(/[–—]/)
        }
    })

    it('covers the create tool of every natural-key kind in the stack registry', () => {
        const registry = readFileSync(resolve(__dirname, '../../../../packages/sdk/src/stack/registry.ts'), 'utf8')
        const naturalKeyKinds = new Map<string, string>()
        for (const entry of registry.split(/\n    \{/).slice(1)) {
            const kind = /kind: '([a-z_]+)'/.exec(entry)?.[1]
            const tool = /tool: '([a-z0-9-]+)'/.exec(entry)?.[1]
            if (kind && tool && entry.includes('naturalKey:')) {
                naturalKeyKinds.set(kind, tool)
            }
        }
        // A context page's tool writes a page whether or not it exists, so it is a write, not a create.
        const writesNotCreates: Record<string, string> = { context_page: 'context-wiki-page-update' }

        expect([...naturalKeyKinds.keys()].sort()).toEqual(Object.keys(CREATE_TOOLS_BY_KIND).sort())
        for (const [kind, tool] of naturalKeyKinds) {
            if (writesNotCreates[kind]) {
                expect(tool).toBe(writesNotCreates[kind])
                expect(CREATE_TOOLS_BY_KIND[kind]).not.toContain(tool)
            } else {
                expect(CREATE_TOOLS_BY_KIND[kind]?.[0]).toBe(tool)
            }
        }
    })
})
