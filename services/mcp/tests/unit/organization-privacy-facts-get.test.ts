import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PostHogApiError, PostHogPermissionError, PostHogRateLimitError } from '@/lib/errors'
import getPrivacyFactsTool, { classifyReadError, regionFromUrl } from '@/tools/organizations/getPrivacyFacts'
import type { Context } from '@/tools/types'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({ getPostHogClient: () => ({ captureException }) }))

type Responder = (path: string) => unknown

function createMockContext(respond: Responder, publicBaseUrl = 'https://us.posthog.com'): Context {
    const request = vi.fn(async ({ path }: { path: string }) => {
        const result = respond(path)
        if (result instanceof Error) {
            throw result
        }
        return result
    })
    return {
        api: { request, publicBaseUrl },
        cache: {},
        stateManager: {
            getProjectId: async () => '2',
            getOrgID: async () => 'org-1',
            getApiKey: async () => ({ suppress_analytics: false }),
        },
        env: {},
        sessionManager: {},
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
}

const denied = (detail: string, missingScope?: string): PostHogPermissionError =>
    new PostHogPermissionError({ detail, missingScope, url: 'https://us.posthog.com/api/x/', method: 'GET' })

const happyPath: Responder = (path) => {
    if (path === '/api/projects/2/') {
        return {
            id: 2,
            name: 'Prod',
            organization: 'org-1',
            api_host: 'https://eu.i.posthog.com',
            anonymize_ips: true,
            session_recording_retention_period: '90d',
            logs_settings: { retention_days: 30 },
            api_token: 'phc_should_not_leak',
        }
    }
    if (path === '/api/organizations/org-1/') {
        return {
            id: 'org-1',
            name: 'Acme',
            membership_level: 8,
            has_signed_baa: false,
            customer_id: 'cus_secret',
            available_product_features: [
                { key: 'product_analytics_data_retention', limit: 7, unit: 'years' },
                { key: 'sso_enforcement', limit: null },
            ],
        }
    }
    if (path === '/api/organizations/org-1/billing/subscription/') {
        return { billing_plan: 'enterprise', subscription_level: 'paid', customer_id: 'cus_secret' }
    }
    if (path === '/api/organizations/org-1/legal_documents/') {
        return {
            results: [
                { document_type: 'DPA', status: 'signed', created_at: '2026-01-02T00:00:00Z', company_name: 'Acme' },
            ],
        }
    }
    return { retention_months: null }
}

describe('organization-privacy-facts-get', () => {
    const tool = getPrivacyFactsTool()

    beforeEach(() => {
        captureException.mockClear()
    })

    it('is registered under the expected tool name', () => {
        expect(tool.name).toBe('organization-privacy-facts-get')
    })

    it('returns the org facts, the region from the project ingestion host, and links', async () => {
        const context = createMockContext(happyPath)
        const result = (await tool.handler(context, { project_id: 99 } as any)) as any

        const paths = vi.mocked(context.api.request).mock.calls.map(([options]) => options.path)
        expect(paths.filter((path) => path.startsWith('/api/projects/'))).toEqual([
            '/api/projects/2/',
            '/api/projects/2/events_retention/',
        ])
        expect(result.region).toMatchObject({ value: 'eu', basis: 'project_ingestion_host' })
        expect(result.plan).toMatchObject({ status: 'ok', billing_plan: 'enterprise' })
        expect(result.legal_documents).toMatchObject({ status: 'ok', dpa: { status: 'signed' }, baa: null })
        expect(result.project).toMatchObject({ status: 'ok', session_recording_retention_period: '90d' })
        expect(result.organization.plan_entitlements).toEqual([
            { key: 'product_analytics_data_retention', limit: 7, unit: 'years' },
        ])
        expect(result.sources.subprocessors).toBe('https://posthog.com/subprocessors')

        const serialized = JSON.stringify(result)
        expect(serialized).not.toContain('cus_secret')
        expect(serialized).not.toContain('phc_should_not_leak')
        expect(serialized).not.toContain('company_name')
    })

    it('tells a non-admin to ask an admin or owner when legal documents are denied, and keeps the rest', async () => {
        const respond: Responder = (path) =>
            path.endsWith('/legal_documents/')
                ? denied('Your organization access level is insufficient.')
                : happyPath(path)

        const result = (await tool.handler(createMockContext(respond), {})) as any

        expect(result.legal_documents.status).toBe('needs_admin')
        expect(result.legal_documents.message).toMatch(/admins and owners/)
        expect(result.plan.status).toBe('ok')
    })

    it('falls back to the MCP host for the region when the project cannot be read', async () => {
        const respond: Responder = (path) => (path === '/api/projects/2/' ? denied('nope') : happyPath(path))

        const result = (await tool.handler(createMockContext(respond, 'https://eu.posthog.com'), {})) as any

        expect(result.region).toMatchObject({ value: 'eu', basis: 'mcp_api_host' })
        expect(result.project.status).toBe('needs_admin')
    })

    it.each([
        [{ status: 'active' }, true],
        [{ status: 'expired' }, false],
        [{ status: 'converted' }, false],
        [null, false],
    ])('reports trial %o as on_trial %s', async (trial, expected) => {
        const respond: Responder = (path) =>
            path.endsWith('/billing/subscription/') ? { billing_plan: 'paid', trial } : happyPath(path)

        const result = (await tool.handler(createMockContext(respond), {})) as any

        expect(result.plan.on_trial).toBe(expected)
    })

    it.each([
        ['a 5xx', new PostHogApiError({ status: 502, statusText: 'Bad Gateway', body: '', url: '', method: 'GET' }), 1],
        ['a bug in the handler', new TypeError('boom'), 1],
        ['a 404', new PostHogApiError({ status: 404, statusText: 'Not Found', body: '', url: '', method: 'GET' }), 0],
        ['a permission denial', denied('nope'), 0],
    ])('captures %s in error tracking only when unexpected, and keeps the rest', async (_, error, captures) => {
        const respond: Responder = (path) => (path.endsWith('/legal_documents/') ? error : happyPath(path))

        const result = (await tool.handler(createMockContext(respond), {})) as any

        expect(captureException.mock.calls).toEqual(
            Array(captures).fill([
                error,
                {
                    properties: {
                        tag: 'mcp',
                        $exception_fingerprint: 'organization-privacy-facts-get',
                        tool: 'organization-privacy-facts-get',
                        suppress_analytics: false,
                    },
                },
            ])
        )
        expect(result.plan.status).toBe('ok')
    })

    it("reads organization facts from the project's organization, not a stale active organization", async () => {
        const context = createMockContext(happyPath)
        context.stateManager.getOrgID = async () => 'org-2'

        const result = (await tool.handler(context, {})) as any

        const paths = vi.mocked(context.api.request).mock.calls.map(([options]) => options.path)
        const orgPaths = paths.filter((path) => path.startsWith('/api/organizations/'))
        expect(orgPaths).toHaveLength(4)
        expect(orgPaths.every((path) => path.startsWith('/api/organizations/org-1/'))).toBe(true)
        expect(result.organization).toMatchObject({ status: 'ok', id: 'org-1' })
    })

    it.each([
        ['cannot be read', denied('nope')],
        ['has no organization', { id: 2, name: 'Prod' }],
        ['is rate limited', new PostHogRateLimitError({ body: '', url: '', method: 'GET', retryAfterSeconds: 30 })],
    ])('skips organization reads when the project %s', async (_, projectResponse) => {
        const respond: Responder = (path) => (path === '/api/projects/2/' ? projectResponse : happyPath(path))
        const context = createMockContext(respond)

        const result = (await tool.handler(context, {})) as any

        const paths = vi.mocked(context.api.request).mock.calls.map(([options]) => options.path)
        expect(paths.some((path) => path.startsWith('/api/organizations/'))).toBe(false)
        for (const section of [
            result.organization,
            result.plan,
            result.legal_documents,
            result.retention.organization_events,
        ]) {
            expect(section).toMatchObject({ status: 'unavailable', message: expect.stringContaining('switch-project') })
        }
        expect(result.retention.project_events.status).toBe('ok')
        expect(captureException).not.toHaveBeenCalled()
    })
})

describe('classifyReadError', () => {
    it('names the missing scope', () => {
        expect(classifyReadError(denied('x', 'legal_document:read'))).toMatchObject({
            status: 'missing_scope',
            scopes: ['legal_document:read'],
        })
    })

    it('flags project-scoped keys on organization endpoints', () => {
        const error = denied('API keys with scoped projects are only supported on project-based endpoints.')
        expect(classifyReadError(error).status).toBe('needs_org_access')
    })

    it('reports a 404 as unavailable', () => {
        const error = new PostHogApiError({ status: 404, statusText: 'Not Found', body: '', url: '', method: 'GET' })
        expect(classifyReadError(error).status).toBe('unavailable')
    })

    it.each([
        [30, /retry after 30 seconds/],
        [null, /wait before retrying/],
    ])('reports a 429 with Retry-After %s as rate limited with the wait', (retryAfterSeconds, message) => {
        const error = new PostHogRateLimitError({ body: '', url: '', method: 'GET', retryAfterSeconds })
        expect(classifyReadError(error)).toMatchObject({
            status: 'rate_limited',
            retry_after_seconds: retryAfterSeconds,
            message: expect.stringMatching(message),
        })
    })
})

describe('regionFromUrl', () => {
    it.each([
        ['https://us.posthog.com', 'us'],
        ['https://app.posthog.com', 'us'],
        ['https://eu.i.posthog.com', 'eu'],
        ['https://posthog.example.com', undefined],
        [undefined, undefined],
    ])('%s -> %s', (url, expected) => {
        expect(regionFromUrl(url)).toBe(expected)
    })
})
