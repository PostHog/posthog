import type { StateLookupCache } from '@/lib/cache/StateLookupCache'
import { MCPClientProfile } from '@/lib/client-detection'
import { isCloudApi, isLocalApi, MCP_GATEWAY_FLAG } from '@/lib/constants'
import { env } from '@/lib/env'
import { McpSessionResetRequiredError } from '@/lib/errors'
import { EVENT_SOURCE, resolveEventSource } from '@/lib/event-source'
import { MCP_NO_DATA_INSTALL_NOTICE_FLAG, type NoDataAction } from '@/lib/no-data-guard'
import { buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import {
    type EvaluatedFlags,
    evaluateFeatureFlags,
    type FlagEvaluation,
    type FlagGroups,
    resolveFeatureFlagOverrides,
} from '@/lib/posthog/flags'
import type { RequestProperties } from '@/lib/request-properties'
import { filterStaffOnlyTools } from '@/lib/staff-only-tools'
import type { McpMode } from '@/lib/utils'
import { TASKS_CONTEXT_TOOL_NAMES } from '@/tools/tasksContext'
import {
    type FlagGatedTool,
    getFlagGatedTools,
    getRequiredFeatureFlags,
    getScopeGatedTools,
    type ScopeGatedTool,
} from '@/tools/toolDefinitions'
import type { Context, Env, PinnedActiveContext, Tool, ZodObjectAny } from '@/tools/types'

import { McpSessionRedisStore } from './cache/McpSessionRedisStore'
import type { RedisLike } from './cache/RedisCache'
import { MCP_EXEC_SKILLS_FEATURE_FLAG } from './constants'
import { MCP_INTENT_PROMPT_FLAG, resolveIntentPrompt } from './intent-prompt'
import {
    type InterviewRecruitmentConfig,
    type InterviewRecruitmentDiagnostics,
    type InterviewRecruitmentUnavailableReason,
    resolveInterviewRecruitmentConfig,
    MCP_INTERVIEW_RECRUITMENT_FLAG,
} from './interview-recruitment'
import {
    buildMCPRequestContext,
    getEffectiveMCPClientContext,
    getEffectiveMCPClientIdentity,
    type MCPRequestContext,
    type MCPSessionContext,
} from './mcp-context'
import { RequestContext } from './request-context'
import type { ToolCatalog } from './tool-catalog'

// ─── Per-request resolved state ───

export interface ResolvedState {
    reqCtx: RequestContext
    context: Context
    useSingleExec: boolean
    viaMcpStore?: boolean | undefined
    toolFeatureFlags: EvaluatedFlags | undefined
    interviewRecruitmentConfig?: InterviewRecruitmentConfig
    intentPrompt?: string
    interviewRecruitmentUnavailableReason?: InterviewRecruitmentUnavailableReason
    interviewRecruitmentDiagnostics?: InterviewRecruitmentDiagnostics
    apiKeyScopes: string[]
    isImpersonated?: boolean
    suppressAnalytics?: boolean
    projectHasData?: boolean | undefined
    /** Set on the per-call state when the no-data notice blocked or warned this call. */
    noDataAction?: NoDataAction | undefined
    oauthClientId: string | undefined
    clientProfile: MCPClientProfile
    requestContext: MCPRequestContext
    sessionContext: MCPSessionContext | null
    allTools: Tool<ZodObjectAny>[]
    scopeGatedTools: ScopeGatedTool[]
    flagGatedTools: FlagGatedTool[]
    /**
     * The tools a scout run with a picked tool list holds, from token introspection.
     * Undefined means no per-tool policy. Every other tool is hidden, and exec refuses it
     * as `tool_not_granted`.
     */
    heldTools?: ReadonlySet<string> | undefined
    /** The task a sandbox token is bound to, from token introspection. */
    sandboxTaskId?: string | undefined
    /**
     * Whether the caller's team may reach third-party MCP tools through `exec`.
     * Gated on the same flag as the gateway UI — the tools are the gateway's payoff,
     * so they roll out together. Also forced off in read-only mode: a connected
     * server's tools can mutate and PostHog can't prove otherwise, so the catalog's
     * read-only filter has no equivalent to apply to them.
     *
     * Deliberately not folded into `allTools`: `instructions.ts` looks every entry up in
     * the static tool-definition registry (which throws on an unknown name) and renders
     * the full roster into the instructions payload.
     */
    gatewayToolsEnabled: boolean
    gatewayToolFilter?: Pick<RequestProperties, 'tools' | 'features' | 'excludeTools'> | undefined
    distinctId: string
    renderUiEnabled: boolean
}

// ─── Pure helpers ───

export function resolveMode(args: { mode: McpMode | undefined; clientProfile: MCPClientProfile }): {
    mode: McpMode
    useSingleExec: boolean
} {
    const { mode, clientProfile } = args
    // CLI (single-exec) is the default; only allow-listed clients (Cursor) keep
    // the full per-tool roster, and an explicit ?mode= / x-posthog-mcp-mode
    // header always wins over auto-detection.
    const resolved: McpMode = mode ?? (clientProfile.isToolsModeClient() ? 'tools' : 'cli')
    return { mode: resolved, useSingleExec: resolved === 'cli' }
}

export function tasksContextToolsToExclude(clientProfile: MCPClientProfile, taskId: string | undefined): string[] {
    return clientProfile.isPostHogCodeConsumer() && taskId ? [] : [...TASKS_CONTEXT_TOOL_NAMES]
}

/**
 * Which navigation switch tools to hide given the context the client explicitly
 * pinned via request params.
 *
 * Pinning fixes the *default* active context — it must not disable navigation.
 * Only an explicitly pinned organization is a hard lock: the client asked to
 * operate inside one org, so `switch-organization` is dropped while project
 * switching stays available. A pinned *project* excludes nothing, because the
 * documented cross-org flow depends on it: from an active project an agent
 * resolves an org via `organizations-get`, calls `switch-organization`, then
 * `switch-project` to reach a project in another organization (see the
 * `switch-project` tool description). Excluding the switch tools on a project
 * pin — which nearly every connection sends — made that flow impossible.
 *
 * Note this only affects keys that can act across orgs. A project-scoped key
 * (`scoped_teams`) never sees `switch-organization` regardless, because
 * `getToolsForFeatures` independently strips every `organization:*` tool the
 * backend would 403 for such a token.
 */
export function switchToolsToExclude(pinned: { organizationId?: string | undefined }): string[] {
    return pinned.organizationId ? ['switch-organization'] : []
}

// ─── Resolver ───

// Task origins whose sandbox mounts every shared gateway server as its own MCP server
// (`mcp__<server>__<tool>`). Surfacing the same tools through `exec` as `<slug>__<tool>` gives
// those agents a second, member-scoped name for each tool — one that resolves for a person
// running the task interactively and comes back empty for the service account the scheduled
// run uses, so instructions learned on one path silently fail on the other.
const DIRECT_GATEWAY_MOUNT_ORIGINS: ReadonlySet<string> = new Set(['signals_scout'])

function mountsGatewayServersDirectly(taskOriginProduct: string | undefined): boolean {
    return taskOriginProduct !== undefined && DIRECT_GATEWAY_MOUNT_ORIGINS.has(taskOriginProduct)
}

export class RequestStateResolver {
    private readonly catalog: ToolCatalog
    private readonly redis: RedisLike
    private readonly env: Env

    constructor(catalog: ToolCatalog, redis: RedisLike, env: Env) {
        this.catalog = catalog
        this.redis = redis
        this.env = env
    }

    async resolve(props: RequestProperties, lookups?: StateLookupCache): Promise<ResolvedState> {
        const requestContext = buildMCPRequestContext(props)
        const reqCtx = new RequestContext(this.redis, this.env, props, requestContext, lookups)

        const { features, tools, organizationId, projectId, readOnly } = props
        const pinned = await this.resolvePinnedContext(reqCtx, { organizationId, projectId })
        reqCtx.setPinnedContext(pinned)

        // Start Redis reads only when Promise.all can observe their timeout rejections.
        // A pinned request never writes a default into the token selection that other sessions share.
        const [context, sessionContext, storedProjectId] = await Promise.all([
            reqCtx.getContext(),
            this.resolveSessionContext(requestContext),
            pinned ? undefined : reqCtx.tokenCache.get('projectId'),
        ])
        const needsDefaultContext = pinned
            ? pinned.sessionScoped && !pinned.orgId && !pinned.projectId
            : !storedProjectId
        if (needsDefaultContext) {
            await context.stateManager.setDefaultOrganizationAndProject()
        }
        const clientContext = getEffectiveMCPClientContext(requestContext, sessionContext)

        // MCP_GATEWAY_FLAG gates no tool of its own — it gates the third-party tools `exec`
        // resolves — so the tool-definition scan can't discover it; join it in explicitly.
        // MCP_EXEC_SKILLS_FEATURE_FLAG gates the `learn` skill commands the same way.
        const allFlagKeys = [
            ...new Set([
                ...getRequiredFeatureFlags(),
                MCP_GATEWAY_FLAG,
                MCP_EXEC_SKILLS_FEATURE_FLAG,
                MCP_INTERVIEW_RECRUITMENT_FLAG,
                MCP_INTENT_PROMPT_FLAG,
                MCP_NO_DATA_INSTALL_NOTICE_FLAG,
            ]),
        ]

        const flagAnalyticsContext = await reqCtx.safelyGetAnalyticsContext(context)
        const flagGroups = flagAnalyticsContext ? buildMCPAnalyticsGroups(flagAnalyticsContext) : undefined

        const [{ flags: allFlags, payloads }, _apiKey, distinctId] = await Promise.all([
            this.resolveAllFlags(reqCtx, allFlagKeys, flagGroups),
            context.stateManager.getApiKey(),
            reqCtx.getDistinctId(),
        ])
        const [oauthClientName, oauthClientId] = await Promise.all([
            reqCtx.tokenCache.get('clientName'),
            reqCtx.tokenCache.get('oauthClientId'),
        ])
        props.suppressAnalytics = _apiKey?.suppress_analytics === true
        const liveClient = getEffectiveMCPClientIdentity(requestContext, sessionContext)
        const source = resolveEventSource({
            mcpConsumer: liveClient.mcpConsumer,
            clientUserAgent: props.clientUserAgent,
            apiKeyScopes: _apiKey?.scopes,
            oauthClientId: oauthClientId || undefined,
        })

        // Dev/test-only overrides win over evaluated values (no-op in production).
        const overrides = resolveFeatureFlagOverrides(props.featureFlagOverrides)
        const mergedFlags = { ...allFlags, ...overrides }
        let recruitmentPayload = payloads[MCP_INTERVIEW_RECRUITMENT_FLAG]
        if (
            recruitmentPayload === undefined &&
            isLocalApi() &&
            (env.NODE_ENV === 'development' || env.NODE_ENV === 'test') &&
            overrides[MCP_INTERVIEW_RECRUITMENT_FLAG]
        ) {
            try {
                recruitmentPayload = JSON.parse(env.MCP_INTERVIEW_RECRUITMENT_PAYLOAD ?? '')
            } catch {
                // Local opt-in still requires explicit, valid invitation content.
            }
        }
        const recruitmentFlagValue = mergedFlags[MCP_INTERVIEW_RECRUITMENT_FLAG]
        let interviewRecruitmentUnavailableReason: InterviewRecruitmentUnavailableReason | undefined
        if (source !== EVENT_SOURCE.MCP) {
            interviewRecruitmentUnavailableReason = 'surface_excluded'
        } else if (_apiKey?.scopes?.includes('internal_run:read')) {
            interviewRecruitmentUnavailableReason = 'internal_run'
        } else if (props.taskId || props.taskOriginProduct) {
            interviewRecruitmentUnavailableReason = 'task_bound'
        } else if (recruitmentFlagValue === undefined) {
            interviewRecruitmentUnavailableReason = 'flag_unavailable'
        } else if (recruitmentFlagValue === false) {
            interviewRecruitmentUnavailableReason = 'flag_disabled'
        }
        const interviewRecruitmentConfig = interviewRecruitmentUnavailableReason
            ? undefined
            : resolveInterviewRecruitmentConfig(recruitmentFlagValue, recruitmentPayload)
        if (!interviewRecruitmentUnavailableReason && !interviewRecruitmentConfig) {
            interviewRecruitmentUnavailableReason = 'invalid_configuration'
        }
        // Preserve variant strings (and `undefined` for unevaluated flags) — the
        // tool filter needs raw values to support `feature_flag_variant` matching.
        // Include override keys so a forced flag reaches the tool/instructions layer
        // even when no catalog tool referenced it.
        const flagKeysForState = [...new Set([...allFlagKeys, ...Object.keys(overrides)])]
        const toolFeatureFlags = Object.fromEntries(flagKeysForState.map((k) => [k, mergedFlags[k]]))
        const intentPrompt =
            source === EVENT_SOURCE.MCP && !_apiKey?.is_impersonated && !props.suppressAnalytics
                ? resolveIntentPrompt(mergedFlags[MCP_INTENT_PROMPT_FLAG], payloads[MCP_INTENT_PROMPT_FLAG])
                : undefined

        const clientProfile = new MCPClientProfile({
            clientName: clientContext.mcpClientName,
            clientVersion: clientContext.mcpClientVersion,
            consumer: clientContext.mcpConsumer,
            oauthClientName: oauthClientName || undefined,
            vendorClient: clientContext.mcpVendorClient,
            userAgent: props.clientUserAgent,
        })

        // `render-ui` is only meaningful for MCP Apps hosts (Claude web/desktop) that can
        // mount its iframe. Single-exec CLI clients like Claude Code can't mount it, so the
        // tool's advertisement and execution stay gated on the UI-host check.
        const renderUiEnabled = clientProfile.isClaudeUiHost()

        const { mode: resolvedMode, useSingleExec } = resolveMode({
            mode: requestContext.mode,
            clientProfile,
        })
        requestContext.mode = resolvedMode
        reqCtx.setMcpContexts(requestContext, sessionContext)
        props.mode = resolvedMode

        const apiKeyScopes = _apiKey?.scopes ?? []
        const apiKeyScopedTeams = _apiKey?.scoped_teams ?? []
        const aiConsentGiven = await context.stateManager.getAiConsentGiven()
        const availableFeatures = await context.stateManager.getAvailableFeatures()
        const isCloud = isCloudApi()

        const excludeTools = [
            ...switchToolsToExclude({ organizationId }),
            ...tasksContextToolsToExclude(clientProfile, props.taskId),
            ...(apiKeyScopes.includes('internal_run:read') ? ['tasks-run-create', 'tasks-create-and-run'] : []),
            ...(props.excludeTools ?? []),
        ]

        const filterOptions = {
            features,
            tools,
            excludeTools,
            readOnly,
            featureFlags: toolFeatureFlags,
            scopedTeams: apiKeyScopedTeams,
            aiConsentGiven: aiConsentGiven ?? undefined,
            availableFeatures,
            isCloud,
        }
        // The held set is a server-derived ceiling on top of every other filter, so a tool
        // outside it is neither listed nor offered as a gated hint the agent could chase.
        const heldTools = _apiKey?.mcp_allowed_tools ? new Set(_apiKey.mcp_allowed_tools) : undefined
        const isHeld = (tool: { name: string }): boolean => !heldTools || heldTools.has(tool.name)

        // Staff-only tools (OAuth-hidden scopes) need the extra explicit-scope +
        // is_staff gate on top of the catalog's plain scope filter.
        const allTools = (
            await filterStaffOnlyTools(
                this.catalog.getFilteredTools({ ...filterOptions, scopes: apiKeyScopes }),
                _apiKey ?? { scopes: [] },
                () => context.stateManager.getUser()
            )
        ).filter(isHeld)
        // Scope-gated hints are only consumed by the exec `search` command, which
        // only exists in single-exec mode — skip the extra scan otherwise.
        const scopeGatedTools = useSingleExec ? getScopeGatedTools(apiKeyScopes, filterOptions).filter(isHeld) : []
        // Only exec redirects a call to a gated tool; tools mode just omits it.
        const flagGatedTools = useSingleExec ? getFlagGatedTools(filterOptions).filter(isHeld) : []

        return {
            reqCtx,
            context,
            useSingleExec,
            viaMcpStore: props.viaMcpStore,
            toolFeatureFlags,
            interviewRecruitmentConfig,
            intentPrompt,
            interviewRecruitmentUnavailableReason,
            apiKeyScopes,
            isImpersonated: _apiKey?.is_impersonated === true,
            suppressAnalytics: props.suppressAnalytics,
            projectHasData: flagAnalyticsContext?.projectHasData,
            oauthClientId: oauthClientId || undefined,
            clientProfile,
            requestContext,
            sessionContext,
            allTools,
            scopeGatedTools,
            flagGatedTools,
            gatewayToolFilter: { tools, features, excludeTools },
            heldTools,
            sandboxTaskId: _apiKey?.sandbox_task_id,
            gatewayToolsEnabled:
                useSingleExec &&
                !readOnly &&
                mergedFlags[MCP_GATEWAY_FLAG] === true &&
                !mountsGatewayServersDirectly(props.taskOriginProduct),
            distinctId,
            renderUiEnabled,
        }
    }

    /**
     * Capture the session selection once per request so another connection's
     * switches cannot redirect an in-flight call. A resent pin preserves switches;
     * a changed pin replaces the whole selection. Clients may send pins only on initialize.
     */
    private async resolvePinnedContext(
        reqCtx: RequestContext,
        pin: { organizationId?: string | undefined; projectId?: string | undefined }
    ): Promise<PinnedActiveContext | undefined> {
        const { organizationId, projectId } = pin
        const hasPin = Boolean(organizationId || projectId)

        const sessionCache = reqCtx.sessionScopedCache
        if (!sessionCache) {
            return hasPin ? { pin, sessionScoped: false, orgId: organizationId, projectId } : undefined
        }

        const legacyCache = reqCtx.legacySessionScopedCache
        const [appliedPinOrg, appliedPinProject, activeOrg, activeProject, defaults, legacyPinOrg, legacyPinProject] =
            await Promise.all([
                sessionCache.get('appliedPinOrgId'),
                sessionCache.get('appliedPinProjectId'),
                sessionCache.get('activeOrgId'),
                sessionCache.get('activeProjectId'),
                sessionCache.get('defaultContext'),
                legacyCache?.get('appliedPinOrgId'),
                legacyCache?.get('appliedPinProjectId'),
            ])
        // A pin marker under the former key means a pinned session from before the
        // key included the credential. Its saved switch would be lost silently, so
        // stop before any tool runs. Legacy state without a pin marker never changed
        // the selection, so it needs no reset.
        const hasSessionState = Boolean(appliedPinOrg || appliedPinProject || activeOrg || activeProject || defaults)
        if (!hasSessionState && (legacyPinOrg || legacyPinProject)) {
            throw new McpSessionResetRequiredError()
        }
        // These keys carry a write-based TTL, but the MCP session they belong to
        // renews its own context store on every request. Renew them too, so a
        // switch recorded early in a long-lived session does not expire before
        // the session ends and read back as a missing marker — which reads as a
        // changed pin, discards the switch, and reverts to the pin mid-session.
        await sessionCache.refreshTtl([
            'appliedPinOrgId',
            'appliedPinProjectId',
            'activeOrgId',
            'activeProjectId',
            'defaultContext',
            'defaultProjectId',
        ])

        // An omitted pin is not a changed pin: keep the session's saved context.
        if (!hasPin) {
            const useDefaults =
                activeOrg === undefined && activeProject === undefined && !appliedPinOrg && !appliedPinProject
            return {
                pin: { organizationId: appliedPinOrg, projectId: appliedPinProject },
                sessionScoped: true,
                orgId:
                    activeOrg !== undefined
                        ? (activeOrg ?? undefined)
                        : (appliedPinOrg ?? (useDefaults ? defaults?.organizationId : undefined)),
                projectId:
                    activeProject !== undefined
                        ? (activeProject ?? undefined)
                        : (appliedPinProject ?? (useDefaults ? defaults?.projectId?.toString() : undefined)),
            }
        }

        const pinChanged = appliedPinOrg !== organizationId || appliedPinProject !== projectId

        let overrideOrg = activeOrg
        let overrideProject = activeProject
        if (pinChanged) {
            overrideOrg = undefined
            overrideProject = undefined
            await Promise.all([
                sessionCache.delete('activeOrgId'),
                sessionCache.delete('activeProjectId'),
                organizationId ? undefined : sessionCache.delete('appliedPinOrgId'),
                projectId ? undefined : sessionCache.delete('appliedPinProjectId'),
                sessionCache.setMany({
                    ...(organizationId ? { appliedPinOrgId: organizationId } : {}),
                    ...(projectId ? { appliedPinProjectId: projectId } : {}),
                }),
            ])
        }

        return {
            pin,
            sessionScoped: true,
            orgId: overrideOrg !== undefined ? (overrideOrg ?? undefined) : organizationId,
            projectId: overrideProject !== undefined ? (overrideProject ?? undefined) : projectId,
        }
    }

    private async resolveSessionContext(requestContext: MCPRequestContext): Promise<MCPSessionContext | null> {
        if (!requestContext.mcpSessionId) {
            return null
        }
        return new McpSessionRedisStore(this.redis, requestContext.mcpSessionId).resolve(requestContext)
    }

    private async resolveAllFlags(
        reqCtx: RequestContext,
        flagKeys: string[],
        groups?: FlagGroups
    ): Promise<FlagEvaluation> {
        if (flagKeys.length === 0) {
            return { flags: {}, payloads: {} }
        }
        // Enable product surfaces locally because the analytics flag client is disabled there.
        // Recruitment and intent experiments stay off so ordinary development keeps the default behavior.
        if (isLocalApi()) {
            return {
                flags: Object.fromEntries(
                    flagKeys.map((key) => [
                        key,
                        key !== MCP_INTERVIEW_RECRUITMENT_FLAG && key !== MCP_INTENT_PROMPT_FLAG,
                    ])
                ),
                payloads: {},
            }
        }
        try {
            const distinctId = await reqCtx.getDistinctId()
            const key = JSON.stringify([
                'featureFlags',
                distinctId,
                Object.entries(groups ?? {}).sort(([a], [b]) => a.localeCompare(b)),
                [...flagKeys].sort(),
            ])
            return await reqCtx.lookups.get(reqCtx.tokenCache.scope, key, () =>
                evaluateFeatureFlags(flagKeys, distinctId, groups)
            )
        } catch {
            return { flags: {}, payloads: {} }
        }
    }
}
