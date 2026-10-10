import { randomBytes, randomUUID } from 'node:crypto'
import { z } from 'zod'

import { ApiClient } from '@/api/client'
import { PinnedContextSwitchError } from '@/lib/errors'
import { SessionManager } from '@/lib/SessionManager'
import { NonceLedger, PayloadStash, SignedStateCodec } from '@/lib/signed-state'
import { StateManager } from '@/lib/StateManager'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { TOOL_MAP } from '@/tools/index'
import { mergeToolFactories } from '@/tools/mergeToolFactories'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { CachedOrg, Context, State } from '@/tools/types'

import type { SharedToolSession, SharedToolSessionOptions } from '../../../packages/sdk/src/runtime/shared-tools'
import type { JsonValue, ResponseMeta } from '../../../packages/sdk/src/types'
import { MemoryCache } from './client-cache'
import { ConfirmationStore } from './confirmation-store'
import { sdkHost } from './host-state'

const factories = mergeToolFactories({ generated: GENERATED_TOOL_MAP, handwritten: TOOL_MAP })

export function getToolSchemas(): Record<string, object> {
    return Object.fromEntries(
        Object.entries(factories).map(([name, factory]) => [
            name,
            z.toJSONSchema(factory().schema, { io: 'input', reused: 'ref', unrepresentable: 'any' }),
        ])
    )
}

export function createToolSession(options: SharedToolSessionOptions): SharedToolSession {
    const cache = new MemoryCache<State>(randomUUID())
    const sessionId = randomUUID()
    const store = new ConfirmationStore()
    const confirmation = {
        codec: new SignedStateCodec(randomBytes(32)),
        stash: new PayloadStash(store),
        ledger: new NonceLedger(store),
    }
    let activeOrganization = options.organizationId

    return {
        async execute(toolName, input, signal) {
            const factory = factories[toolName]
            if (!factory) {
                throw new Error(`Unknown PostHog tool: ${toolName}`)
            }
            const tool = factory()
            const params = tool.schema.parse(input)
            let meta: ResponseMeta = { status: 200 }
            let requestProject: Promise<string> | undefined
            let requestOrganization = activeOrganization
            let feedbackError: Error | undefined

            class DirectApi extends ApiClient {
                protected override async fetch(url: string, init: RequestInit = {}): Promise<Response> {
                    if (signal.aborted) {
                        throw new DOMException('The PostHog call was canceled.', 'AbortError')
                    }
                    let response: Response
                    try {
                        response = await options.fetch(url, init, signal)
                    } catch (cause) {
                        if (signal.aborted) {
                            throw new DOMException('The PostHog call was canceled.', 'AbortError')
                        }
                        throw cause
                    }
                    const requestId = response.headers.get('x-request-id')
                    meta = { status: response.status, ...(requestId ? { requestId } : {}) }
                    return response
                }
            }

            const api = new DirectApi({
                baseUrl: options.baseUrl,
                publicBaseUrl: options.publicBaseUrl,
                apiToken: options.token ?? '',
                taskId: options.taskId,
            })
            class ClientState extends StateManager {
                override async getProjectId(): Promise<string> {
                    requestProject ??= options.getProjectId(signal).then(String)
                    return requestProject
                }

                override async getOrgID(): Promise<string> {
                    if (requestOrganization) {
                        return requestOrganization
                    }
                    const projectId = await this.getProjectId().catch(() => undefined)
                    if (projectId) {
                        const project = await api.projects().get({ projectId })
                        if (project.success && project.data.organization) {
                            requestOrganization = project.data.organization
                            return project.data.organization
                        }
                    }
                    const user = await this.getUser()
                    if (!user.organization?.id) {
                        throw new Error(
                            'Set organizationId or select an organization with organizations.switchOrganization.'
                        )
                    }
                    requestOrganization = user.organization.id
                    return requestOrganization
                }

                override async setActiveContext(updates: { orgId?: string; projectId?: string }): Promise<void> {
                    if (signal.aborted) {
                        throw signal.reason
                    }
                    options.setContext({
                        ...(updates.orgId ? { organizationId: updates.orgId } : {}),
                        ...(updates.projectId ? { projectId: Number(updates.projectId) } : {}),
                    })
                    if (updates.orgId) {
                        activeOrganization = updates.orgId
                        requestOrganization = updates.orgId
                    }
                    if (updates.projectId) {
                        requestProject = Promise.resolve(updates.projectId)
                    }
                    await super.setActiveContext(updates)
                }

                override async getCachedOrFetchOrg(): Promise<CachedOrg | undefined> {
                    const orgId = await this.getOrgID()
                    const result = await api.organizations().get({ orgId })
                    return result.success ? result.data : undefined
                }

                override async getAiConsentGiven(): Promise<boolean | undefined> {
                    const orgId = await this.getOrgID()
                    const user = await this.getUser().catch(() => undefined)
                    if (user?.organization?.id === orgId) {
                        return user.organization.is_ai_data_processing_approved === true
                    }
                    const organization = await api.organizations().get({ orgId })
                    return organization.success ? organization.data.is_ai_data_processing_approved === true : undefined
                }
            }
            const stateManager = new ClientState(
                cache,
                api,
                options.pinnedProjectId === undefined
                    ? undefined
                    : {
                          pin: { projectId: String(options.pinnedProjectId) },
                          projectId: String(options.pinnedProjectId),
                          sessionScoped: false,
                      }
            )
            const context: Context = {
                api,
                cache,
                stateManager,
                sessionManager: new SessionManager(cache),
                env: {
                    POSTHOG_API_BASE_URL: options.baseUrl,
                    POSTHOG_PUBLIC_URL: options.publicBaseUrl,
                    MCP_APPS_BASE_URL: undefined,
                    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
                    POSTHOG_UI_APPS_TOKEN: undefined,
                    POSTHOG_ANALYTICS_API_KEY: undefined,
                    POSTHOG_ANALYTICS_HOST: undefined,
                },
                getDistinctId: async () => sessionId,
                trackEvent: async (_event, properties) => {
                    try {
                        await options.feedback?.(JSON.parse(JSON.stringify(properties)) as Record<string, JsonValue>)
                    } catch (cause) {
                        // MCP feedback is best-effort; an SDK callback failure must not report delivery.
                        feedbackError = cause instanceof Error ? cause : new Error(String(cause))
                    }
                },
            }
            try {
                if (toolName === 'agent-feedback' && !options.feedback) {
                    throw Object.assign(
                        new Error('Set the feedback callback on createPostHogClient to receive agent feedback.'),
                        { kind: 'configuration' }
                    )
                }
                if (
                    getToolDefinition(toolName).requires_ai_consent &&
                    (await stateManager.getAiConsentGiven()) !== true
                ) {
                    throw Object.assign(
                        new Error('Approve AI data processing in the organization settings before calling this tool.'),
                        { status: 403 }
                    )
                }
                let data = await sdkHost.run({ confirmation }, () => tool.handler(context, params))
                if (feedbackError) {
                    throw feedbackError
                }
                if (toolName === 'agent-feedback' && data && typeof data === 'object') {
                    data = { ...data, message: 'Feedback was delivered to the configured SDK feedback callback.' }
                }
                if (
                    data &&
                    typeof data === 'object' &&
                    'isError' in data &&
                    data.isError === true &&
                    'content' in data &&
                    Array.isArray(data.content)
                ) {
                    throw new Error(
                        data.content.map((item) => (typeof item?.text === 'string' ? item.text : '')).join('\n')
                    )
                }
                return { data: data as JsonValue, meta }
            } catch (cause) {
                if (cause instanceof PinnedContextSwitchError) {
                    throw Object.assign(
                        new Error(
                            'This client has an immutable project scope. Use client.project(id) to select another project.'
                        ),
                        { kind: 'configuration', sdkMeta: meta, cause }
                    )
                }
                const error = cause instanceof Error ? cause : new Error(String(cause))
                throw Object.assign(error, { sdkMeta: meta })
            }
        },
    }
}
