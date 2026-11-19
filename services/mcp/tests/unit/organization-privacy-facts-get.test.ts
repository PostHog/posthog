import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError, PostHogPermissionError } from '@/lib/errors'
import getPrivacyFactsTool, { classifyReadError, regionFromUrl } from '@/tools/organizations/getPrivacyFacts'
import type { Context } from '@/tools/types'

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
                { key: 'product_analytics_data_retention', limit: 7 },
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

    it('is registered under the expected tool name', () => {
        expect(tool.name).toBe('organization-privacy-facts-get')
    })

    it('returns the org facts, the region from the project ingestion host, and links', async () => {
        const result = (await tool.handler(createMockContext(happyPath), {})) as any

        expect(result.region).toMatchObject({ value: 'eu', basis: 'project_ingestion_host' })
        expect(result.plan).toMatchObject({ status: 'ok', billing_plan: 'enterprise' })
        expect(result.legal_documents).toMatchObject({ status: 'ok', dpa: { status: 'signed' }, baa: null })
        expect(result.project).toMatchObject({ status: 'ok', session_recording_retention_period: '90d' })
        expect(result.organization.plan_entitlements).toEqual([{ key: 'product_analytics_data_retention', limit: 7 }])
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
