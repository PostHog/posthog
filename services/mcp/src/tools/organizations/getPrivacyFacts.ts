import { z } from 'zod'

import { findPostHogPermissionError, findRecoverableApiError, isExpectedApiError, PostHogApiError } from '@/lib/errors'
import { POSTHOG_EU_BASE_URL, POSTHOG_US_BASE_URL } from '@/lib/oauth-constants'
import { getPostHogClient } from '@/lib/posthog'
import type { Context, ToolBase } from '@/tools/types'

// Answers "where is our data stored?" and similar privacy questions with the asking org's own
// facts. PostHog-wide facts (subprocessors, hosting, security) stay on posthog.com and are only
// linked here, so this file never goes stale when those pages change.

const schema = z.object({})

/** Links only. The agent opens them before quoting anything from them. */
export const PRIVACY_SOURCE_LINKS = {
    subprocessors: 'https://posthog.com/subprocessors',
    security: 'https://posthog.com/handbook/company/security',
    privacy_docs: 'https://posthog.com/docs/privacy',
    data_storage: 'https://posthog.com/docs/privacy/data-storage',
    dpa: 'https://posthog.com/dpa',
    trust_center: 'https://trust.posthog.com',
    events_retention_docs: 'https://posthog.com/docs/data/events-retention',
    recording_retention_docs: 'https://posthog.com/docs/session-replay/recording-retention',
} as const

export type CloudRegionFact = 'us' | 'eu' | 'unknown'

type Denied =
    | { status: 'missing_scope'; scopes: string[]; message: string }
    | { status: 'needs_org_access'; message: string }
    | { status: 'needs_admin'; message: string }
    | { status: 'unavailable'; message: string }
    | { status: 'rate_limited'; retry_after_seconds: number | null; message: string }
    | { status: 'error'; message: string }

export type Section<T> = ({ status: 'ok' } & T) | Denied

const ASK_ADMIN =
    'PostHog denied this read for the current user. Ask an organization admin or owner to look it up in PostHog for you.'

class NoProjectOrganizationError extends Error {}

/** Turn a failed read into a status the agent can relay, instead of failing the whole tool. */
export function classifyReadError(error: unknown, adminOnlyNote?: string): Denied {
    if (error instanceof NoProjectOrganizationError) {
        return {
            status: 'unavailable',
            message:
                "Organization settings come from the active project's organization, which could not be read. The project section says why. If the project is wrong, call `switch-project`, then retry.",
        }
    }
    const denied = findPostHogPermissionError(error)
    if (denied) {
        const scopes = denied.requiredScopes
        if (scopes?.length) {
            return {
                status: 'missing_scope',
                scopes,
                message: `This API key or OAuth token is missing the ${scopes.map((s) => `'${s}'`).join(', ')} scope. The user can add it to their personal API key, or reconnect the MCP and grant it.`,
            }
        }
        if (denied.detail.includes('API keys with scoped projects')) {
            return {
                status: 'needs_org_access',
                message:
                    'This API key or OAuth token is limited to specific projects, so it cannot read organization settings. A key with organization access can.',
            }
        }
        return { status: 'needs_admin', message: adminOnlyNote ?? ASK_ADMIN }
    }
    const apiError = findRecoverableApiError(error)
    if (apiError instanceof PostHogApiError && apiError.status === 429) {
        const wait = apiError.retryAfterSeconds
        return {
            status: 'rate_limited',
            retry_after_seconds: wait,
            message:
                wait !== null ? `Rate limited; retry after ${wait} seconds.` : 'Rate limited; wait before retrying.',
        }
    }
    if (apiError instanceof PostHogApiError && apiError.status === 404) {
        return { status: 'unavailable', message: 'This instance does not offer this read.' }
    }
    return { status: 'error', message: 'This read failed. Try again, or check it in PostHog.' }
}

async function readSection<T extends object>(
    context: Context,
    read: () => Promise<T>,
    adminOnlyNote?: string
): Promise<Section<T>> {
    try {
        return { status: 'ok' as const, ...(await read()) } as Section<T>
    } catch (error) {
        if (!(error instanceof NoProjectOrganizationError) && !isExpectedApiError(error)) {
            await context.stateManager
                .getApiKey()
                .then((apiKey) =>
                    getPostHogClient().captureException(error, {
                        properties: {
                            tag: 'mcp',
                            $exception_fingerprint: 'organization-privacy-facts-get',
                            tool: 'organization-privacy-facts-get',
                            suppress_analytics: apiKey.suppress_analytics === true,
                            is_impersonated: apiKey.is_impersonated === true,
                        },
                    })
                )
                .catch(() => undefined)
        }
        return classifyReadError(error, adminOnlyNote)
    }
}

const REGION_HOSTS: Record<string, Exclude<CloudRegionFact, 'unknown'>> = {
    'us.posthog.com': 'us',
    'app.posthog.com': 'us',
    'us.i.posthog.com': 'us',
    'eu.posthog.com': 'eu',
    'eu.i.posthog.com': 'eu',
}

export function regionFromUrl(url: string | undefined | null): Exclude<CloudRegionFact, 'unknown'> | undefined {
    if (!url) {
        return undefined
    }
    try {
        return REGION_HOSTS[new URL(url).hostname]
    } catch {
        return undefined
    }
}

// Loose shapes: read only the fields we return, and tolerate the rest (output schemas are permissive).
type OrgResponse = {
    id: string
    name: string
    membership_level?: number | null
    has_signed_baa?: boolean
    is_ai_data_processing_approved?: boolean | null
    is_ai_training_opted_in?: boolean | null
    default_anonymize_ips?: boolean
    available_product_features?: Array<{ key: string; limit?: number | null; unit?: string | null }> | null
}

type SupportPlanResponse = {
    tier: 'paid' | 'trial' | 'free' | 'unknown'
    support_included: boolean | null
}

type LegalDocument = { document_type: string; status: string; created_at: string }

type ProjectResponse = {
    id: number
    name: string
    organization?: string | null
    api_host?: string | null
    anonymize_ips?: boolean
    session_recording_retention_period?: string | null
    is_ai_data_processing_approved?: boolean | null
    logs_settings?: { retention_days?: number | null } | null
}

// Plan entitlement keys whose `limit` answers a retention or BAA question.
const ENTITLEMENT_KEYS = ['product_analytics_data_retention', 'session_replay_data_retention', 'hipaa_baa']

function latestOfType(docs: LegalDocument[], type: string): { status: string; created_at: string } | null {
    const doc = docs.find((d) => d.document_type === type)
    return doc ? { status: doc.status, created_at: doc.created_at } : null
}

export const getPrivacyFactsHandler: ToolBase<typeof schema, Record<string, unknown>>['handler'] = async (
    context: Context
) => {
    const api = context.api
    const projectId = await context.stateManager.getProjectId()
    const projectRead = api.request<ProjectResponse>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(projectId)}/`,
    })
    const project = await readSection(context, async () => {
        const p = await projectRead
        return {
            id: p.id,
            name: p.name,
            ingestion_host: p.api_host ?? null,
            discard_client_ip: p.anonymize_ips ?? null,
            session_recording_retention_period: p.session_recording_retention_period ?? null,
            logs_retention_days: p.logs_settings?.retention_days ?? null,
            ai_data_processing_approved: p.is_ai_data_processing_approved ?? null,
        }
    })
    const orgId = await projectRead.then(
        (p) => p.organization ?? undefined,
        () => undefined
    )
    const org = (path: string): string => `/api/organizations/${encodeURIComponent(String(orgId))}${path}`

    const noOrg = async (): Promise<never> => {
        throw new NoProjectOrganizationError()
    }

    const [organization, plan, legalDocuments, orgEventsRetention, projectEventsRetention] = await Promise.all([
        readSection(context, async () => {
            if (!orgId) {
                return noOrg()
            }
            const o = await api.request<OrgResponse>({ method: 'GET', path: org('/') })
            return {
                id: o.id,
                name: o.name,
                membership_level: o.membership_level ?? null,
                has_signed_baa: o.has_signed_baa ?? null,
                ai_data_processing_approved: o.is_ai_data_processing_approved ?? null,
                ai_training_opted_in: o.is_ai_training_opted_in ?? null,
                default_discard_client_ip: o.default_anonymize_ips ?? null,
                plan_entitlements: (o.available_product_features ?? [])
                    .filter((f) => ENTITLEMENT_KEYS.includes(f.key))
                    .map((f) => ({ key: f.key, limit: f.limit ?? null, unit: f.unit ?? null })),
            }
        }),
        readSection(context, async () => {
            if (!orgId) {
                return noOrg()
            }
            const p = await api.request<SupportPlanResponse>({
                method: 'GET',
                path: org('/posthog_support_plan/'),
            })
            return { tier: p.tier, support_included: p.support_included }
        }),
        readSection(
            context,
            async () => {
                if (!orgId) {
                    return noOrg()
                }
                const page = await api.request<{ results?: LegalDocument[] } | LegalDocument[]>({
                    method: 'GET',
                    path: org('/legal_documents/'),
                })
                const docs = Array.isArray(page) ? page : (page.results ?? [])
                return {
                    dpa: latestOfType(docs, 'DPA'),
                    baa: latestOfType(docs, 'BAA'),
                    note: 'Lists only agreements generated in the PostHog app. An agreement signed another way (for example with an Enterprise contract) does not appear here, so null means "none generated in the app", not "no agreement".',
                }
            },
            'Only organization admins and owners can see legal documents such as the DPA. Ask one of them to check Settings > Legal documents in PostHog.'
        ),
        readSection(context, async () => {
            if (!orgId) {
                return noOrg()
            }
            return await api.request<Record<string, unknown>>({
                method: 'GET',
                path: org('/events_retention_setting/'),
            })
        }),
        readSection(context, async () =>
            api.request<Record<string, unknown>>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(projectId)}/events_retention/`,
            })
        ),
    ])

    const ingestionHost = project.status === 'ok' ? project.ingestion_host : null
    const regionFromProject = regionFromUrl(ingestionHost)
    const regionFromServer = regionFromUrl(api.publicBaseUrl)
    const region: CloudRegionFact = regionFromProject ?? regionFromServer ?? 'unknown'
    const appHost =
        region === 'eu' ? POSTHOG_EU_BASE_URL : region === 'us' ? POSTHOG_US_BASE_URL : (api.publicBaseUrl ?? null)

    return {
        region: {
            value: region,
            basis: regionFromProject ? 'project_ingestion_host' : regionFromServer ? 'mcp_api_host' : 'none',
            app_host: appHost,
            ingestion_host: ingestionHost,
            ...(region === 'unknown'
                ? { note: 'The host is not PostHog Cloud US or EU, so this may be a self-hosted instance.' }
                : {}),
        },
        organization,
        plan,
        legal_documents: legalDocuments,
        retention: {
            organization_events: orgEventsRetention,
            project_events: projectEventsRetention,
        },
        project,
        sources: PRIVACY_SOURCE_LINKS,
    }
}

const tool = (): ToolBase<typeof schema, Record<string, unknown>> => ({
    name: 'organization-privacy-facts-get',
    schema,
    handler: getPrivacyFactsHandler,
})

export default tool
