// Stripe Workflows Custom Action: trigger a PostHog workflow.
//
// This extension implements the `core.workflows.custom_action` interface as a
// Script (TypeScript running in Stripe's sandbox). It uses the PostHog OAuth
// access token that the main app writes to the Stripe Apps Secret Store: the
// egress system injects `Authorization: <posthog_access_token>` (which is
// already stored as "Bearer <token>") on calls to the declared PostHog API
// endpoints. Triggering a workflow uses the unauthenticated public webhook URL
// served by the CDP API service.
//
// Region detection: the script sandbox can't read the `posthog_region` secret
// directly — secrets only flow in via endpoint auth-header injection. Instead
// we probe US first and fall back to EU on 401/403 for authenticated calls,
// and on 404 for the public webhook (the webhook id is a UUID that only exists
// in one region's database). This costs one extra request for EU merchants per
// invocation — acceptable for an interactive Stripe action.
//
// TODO: resolve the US/EU split at the PostHog ingress. There's an in-flight
// effort to route a single `posthog.com` host based on an `X-PostHog-Region`
// header set at the edge. Once that ships, we can collapse `posthog_api_us`
// and `posthog_api_eu` into a single declared endpoint and drop the probing
// fallback — provided Stripe Scripts lets us inject the region header
// alongside the Authorization header on that endpoint. If the ingress ends up
// inferring the region from the bearer token itself (since each token is
// team-scoped and teams live in exactly one region), we don't even need the
// second header and this file just talks to one host.
//
// The `@stripe/apps-extensibility-sdk/extensions-prototype` package is in
// private preview. Until it's installed, we define local interfaces that match
// the shape from STRIPE-WORKFLOWS.md.

interface ExecuteCustomActionRequest {
    customInput?: Record<string, unknown>
}

interface ExecuteCustomActionResponse {
    [key: string]: unknown
}

interface GetFormStateRequest {
    values: Record<string, unknown>
    changedField: string | null
}

interface FieldConfig {
    options?: Array<{ value: string; label: string }>
    schema?: JSONSchemaObject | null
    disabled?: boolean
    hidden?: boolean
    warning?: string
    error?: string
}

interface GetFormStateResponse {
    values?: Record<string, unknown>
    config: Record<string, FieldConfig>
}

interface JSONSchemaObject {
    type: 'object'
    properties: Record<string, JSONSchemaProperty>
}

interface JSONSchemaProperty {
    type: 'string'
    title?: string
    description?: string
    default?: string
}

interface HogFlow {
    id: string
    name: string
    variables?: Array<Record<string, string>>
}

interface PaginatedResponse<T> {
    count: number
    next: string | null
    previous: string | null
    results: T[]
}

class PostHogApiError extends Error {
    status: number

    constructor(message: string, status: number) {
        super(message)
        this.name = 'PostHogApiError'
        this.status = status
    }
}

type Region = 'us' | 'eu'

const REGIONS: readonly Region[] = ['us', 'eu']

const POSTHOG_API_HOSTS: Record<Region, string> = {
    us: 'https://us.posthog.com',
    eu: 'https://eu.posthog.com',
}

const POSTHOG_WEBHOOK_HOSTS: Record<Region, string> = {
    us: 'https://webhooks.us.posthog.com',
    eu: 'https://webhooks.eu.posthog.com',
}

const PAGINATION_PAGE_SIZE = 200
// Hard cap on pagination iterations. 50 pages * 200 items = 10,000 workflows —
// well beyond any realistic merchant, and a safeguard against a malformed
// `next` link spinning forever inside `get_form_state`.
const MAX_PAGINATION_PAGES = 50

function apiHost(region: Region): string {
    return POSTHOG_API_HOSTS[region]
}

function webhookHost(region: Region): string {
    return POSTHOG_WEBHOOK_HOSTS[region]
}

async function fetchJson<T>(url: string): Promise<T> {
    const response = await fetch(url)
    if (!response.ok) {
        const body = await response.text().catch(() => '<unreadable>')
        throw new PostHogApiError(`PostHog request to ${url} failed (${response.status}): ${body}`, response.status)
    }
    return (await response.json()) as T
}

function isAuthError(error: unknown): boolean {
    return error instanceof PostHogApiError && (error.status === 401 || error.status === 403)
}

function isNotFoundError(error: unknown): boolean {
    return error instanceof PostHogApiError && error.status === 404
}

// Try `operation` against each region in turn, returning the first success
// and remembering which region worked. Auth errors (401/403) on an API call
// mean the token isn't valid for that region, so we advance; any other error
// bubbles up.
async function probeRegions<T>(operation: (region: Region) => Promise<T>): Promise<{ region: Region; value: T }> {
    let lastError: unknown
    for (const region of REGIONS) {
        try {
            const value = await operation(region)
            return { region, value }
        } catch (error) {
            lastError = error
            if (isAuthError(error)) {
                continue
            }
            throw error
        }
    }
    throw lastError ?? new PostHogApiError('All PostHog regions rejected the request', 401)
}

async function listWebhookWorkflows(region: Region): Promise<HogFlow[]> {
    const triggerFilter = encodeURIComponent(JSON.stringify({ type: 'webhook' }))
    let nextUrl: string | null =
        `${apiHost(region)}/api/projects/@current/hog_flows/?trigger=${triggerFilter}&limit=${PAGINATION_PAGE_SIZE}`

    const all: HogFlow[] = []
    for (let page = 0; page < MAX_PAGINATION_PAGES && nextUrl !== null; page++) {
        const data: PaginatedResponse<HogFlow> = await fetchJson<PaginatedResponse<HogFlow>>(nextUrl)
        all.push(...data.results)
        nextUrl = data.next
    }
    return all
}

async function retrieveWorkflow(region: Region, workflowId: string): Promise<HogFlow | null> {
    try {
        return await fetchJson<HogFlow>(`${apiHost(region)}/api/projects/@current/hog_flows/${workflowId}/`)
    } catch (error) {
        if (isNotFoundError(error)) {
            return null
        }
        throw error
    }
}

function buildVariablesSchema(workflow: HogFlow | null): JSONSchemaObject | null {
    const variables = workflow?.variables
    if (!variables || variables.length === 0) {
        return null
    }

    const properties: Record<string, JSONSchemaProperty> = {}
    for (const variable of variables) {
        const key = variable['key']
        if (!key) {
            continue
        }
        const property: JSONSchemaProperty = { type: 'string' }
        property.title = variable['label'] ?? key
        if (variable['description']) {
            property.description = variable['description']
        }
        if (variable['default']) {
            property.default = variable['default']
        }
        properties[key] = property
    }

    return { type: 'object', properties }
}

function pruneVariablesToSchema(
    previous: Record<string, unknown> | undefined,
    schema: JSONSchemaObject | null
): Record<string, unknown> {
    if (!schema || !previous) {
        return {}
    }
    const validKeys = new Set(Object.keys(schema.properties))
    const pruned: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(previous)) {
        if (validKeys.has(key)) {
            pruned[key] = value
        }
    }
    return pruned
}

function reconnectErrorMessage(): string {
    return 'PostHog connection expired — reopen the PostHog app in Stripe to reconnect.'
}

async function getFormState(_config: unknown, request: GetFormStateRequest): Promise<GetFormStateResponse> {
    const values: Record<string, unknown> = { ...request.values }

    let workflowsByRegion: { region: Region; value: HogFlow[] }
    try {
        workflowsByRegion = await probeRegions(listWebhookWorkflows)
    } catch (error) {
        return {
            values,
            config: {
                workflow_id: {
                    options: [],
                    error: isAuthError(error) ? reconnectErrorMessage() : 'Failed to list PostHog workflows.',
                },
                variables: { hidden: true },
            },
        }
    }

    const { region, value: workflows } = workflowsByRegion
    const workflowOptions = workflows.map((w) => ({ value: w.id, label: w.name || w.id }))

    const selectedWorkflowId = typeof values.workflow_id === 'string' ? values.workflow_id : null
    const selectedIsKnown = !selectedWorkflowId || workflowOptions.some((option) => option.value === selectedWorkflowId)

    let variablesSchema: JSONSchemaObject | null = null
    let variablesError: string | undefined
    if (selectedWorkflowId) {
        try {
            const workflow = await retrieveWorkflow(region, selectedWorkflowId)
            variablesSchema = buildVariablesSchema(workflow)
        } catch (error) {
            if (isAuthError(error)) {
                variablesError = reconnectErrorMessage()
            } else if (error instanceof PostHogApiError) {
                variablesError = `Failed to load workflow variables (${error.status}).`
            } else {
                variablesError = 'Failed to load workflow variables.'
            }
        }
    }

    // Prune saved variable keys that no longer exist in the selected workflow.
    if (request.changedField === 'workflow_id') {
        values.variables = pruneVariablesToSchema(
            values.variables as Record<string, unknown> | undefined,
            variablesSchema
        )
    }

    const workflowIdConfig: FieldConfig = { options: workflowOptions }
    if (!selectedIsKnown) {
        workflowIdConfig.warning = 'This workflow no longer exists in PostHog.'
    }

    const variablesConfig: FieldConfig = {
        schema: variablesSchema,
        hidden: variablesSchema === null,
    }
    if (variablesError) {
        variablesConfig.error = variablesError
    }

    return {
        values,
        config: {
            workflow_id: workflowIdConfig,
            variables: variablesConfig,
        },
    }
}

async function postWebhook(region: Region, workflowId: string, body: string): Promise<Response> {
    return fetch(`${webhookHost(region)}/public/webhooks/${workflowId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
    })
}

async function execute(_config: unknown, request: ExecuteCustomActionRequest): Promise<ExecuteCustomActionResponse> {
    const input = (request.customInput ?? {}) as Record<string, unknown>
    const workflowId = input.workflow_id
    const variables = (input.variables as Record<string, unknown> | undefined) ?? {}

    if (typeof workflowId !== 'string' || workflowId.length === 0) {
        // 4xx-style permanent failure — no retry (spec §Runtime).
        throw new PostHogApiError('Missing workflow_id in custom action input', 400)
    }

    // The public webhook is unauthenticated, so we can't use 401 to detect
    // region. Instead, try US first and fall back to EU on 404 — a given
    // workflow id exists in exactly one region's database.
    const body = JSON.stringify(variables)
    let lastResponse: Response | null = null
    for (const region of REGIONS) {
        const response = await postWebhook(region, workflowId, body)
        if (response.ok) {
            return {}
        }
        lastResponse = response
        if (response.status !== 404) {
            break
        }
    }

    // Surface the terminal failure so Stripe Workflows can retry on 5xx and
    // short-circuit on 4xx per STRIPE-WORKFLOWS.md §Runtime.
    const status = lastResponse?.status ?? 500
    const errorBody = lastResponse ? await lastResponse.text().catch(() => '<unreadable>') : 'no response'
    throw new PostHogApiError(`PostHog webhook for workflow ${workflowId} returned ${status}: ${errorBody}`, status)
}

const customAction = {
    execute,
    getFormState,
}

export default customAction
