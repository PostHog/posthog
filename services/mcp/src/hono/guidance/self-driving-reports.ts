import { createHash } from 'node:crypto'
import { z } from 'zod'

import { EVENT_SOURCE, resolveEventSource } from '@/lib/event-source'
import { resolveScopePreset } from '@/lib/scope-preset'

import type { RedisLike } from '../cache/RedisCache'
import { resolveSessionKey } from '../mcp-context'
import type { ResolvedState } from '../request-state-resolver'
import type { GuidanceCall, GuidanceNotice } from './engine'
import { MCP_GUIDANCE_ERROR_TRACKING_SD_REPORTS_FLAG } from './rules'

const onboardingStateSchema = z.object({ completed_at: z.string().datetime({ offset: true }).nullable() })
const LOOKUP_TIMEOUT_MS = 1000
const SESSION_TTL_SECONDS = 24 * 60 * 60
const ISSUE_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const REQUIRED_TOOLS = ['inbox-reports-list', 'inbox-reports-retrieve', 'inbox-report-artefacts-list']

async function hasCompletedSelfDrivingSetup(state: ResolvedState, projectId: string): Promise<boolean> {
    try {
        const result = await state.context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/signals/onboarding/`,
            timeoutMs: LOOKUP_TIMEOUT_MS,
            signal: AbortSignal.timeout(LOOKUP_TIMEOUT_MS),
        })
        const parsed = onboardingStateSchema.safeParse(result)
        return parsed.success && parsed.data.completed_at !== null
    } catch {
        return false
    }
}

export async function selfDrivingReportsGuidance(
    redis: RedisLike,
    state: ResolvedState,
    call: GuidanceCall
): Promise<GuidanceNotice | undefined> {
    const projectId = state.analyticsContext?.projectId
    const issueId = call.args?.issueId
    if (
        call.toolName !== 'query-error-tracking-issue' ||
        call.isError ||
        typeof issueId !== 'string' ||
        !ISSUE_ID_PATTERN.test(issueId) ||
        !projectId ||
        typeof state.toolFeatureFlags?.[MCP_GUIDANCE_ERROR_TRACKING_SD_REPORTS_FLAG] !== 'boolean' ||
        state.isTaskBound ||
        state.sandboxTaskId !== undefined ||
        resolveScopePreset(state.apiKeyScopes) !== 'user' ||
        resolveEventSource({
            mcpConsumer: state.clientProfile.consumer,
            clientUserAgent: state.requestContext.clientUserAgent,
            apiKeyScopes: state.apiKeyScopes,
            oauthClientId: state.oauthClientId,
        }) !== EVENT_SOURCE.MCP ||
        !REQUIRED_TOOLS.every((name) => state.allTools.some((tool) => tool.name === name))
    ) {
        return undefined
    }

    const sessionKey =
        state.carriedContextSessionKey ??
        (state.carriedContextHandle === undefined ? resolveSessionKey(state.requestContext) : undefined)
    const marker = sessionKey
        ? `mcp:guidance:sd-reports:${createHash('sha256')
              .update(`${state.distinctId}|${sessionKey}|${projectId}|${issueId.toLowerCase()}`)
              .digest('base64url')}`
        : undefined
    if (marker && (await redis.get(marker))) {
        return undefined
    }
    if (!(await hasCompletedSelfDrivingSetup(state, projectId))) {
        return undefined
    }
    if (marker && (await redis.set(marker, '1', 'EX', SESSION_TTL_SECONDS, 'NX')) !== 'OK') {
        return undefined
    }
    const outcome =
        state.toolFeatureFlags?.[MCP_GUIDANCE_ERROR_TRACKING_SD_REPORTS_FLAG] === true ? 'shown' : 'flag_off'
    return {
        ruleId: 'error-tracking-to-self-driving-reports',
        outcome,
        ...(outcome === 'shown'
            ? {
                  text: [
                      'This project has completed Self-driving setup, so its reports may contain an investigation related to this error.',
                      `Consider calling \`inbox-reports-list\` with \`error_tracking_issue_id: "${issueId}"\` and \`limit: 3\`.`,
                      'Read matching reports with `inbox-reports-retrieve` and their work logs with `inbox-report-artefacts-list`',
                      'before deciding whether the findings or linked PRs help with the current task.',
                      'Also use `inbox-reports-list` with `search` set to the issue name or distinctive error terms',
                      'to investigate related reports, including when the exact lookup returns nothing.',
                      'Check report freshness and whether its evidence covers the current occurrence.',
                      'An exact reference does not prove a linked PR fixes this error; check its scope and latest known state.',
                      'Completed setup does not mean Self-driving is currently running.',
                  ].join(' '),
              }
            : {}),
    }
}
