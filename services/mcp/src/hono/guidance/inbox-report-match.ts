import { createHash } from 'node:crypto'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { formatPrompt } from '@/lib/utils'
import CLOSED_NOTE from '@/templates/guidance/inbox-report-match-closed.md'
import REPORT_MATCH_PROMPT from '@/templates/guidance/inbox-report-match.md'

import type { RedisLike } from '../cache/RedisCache'
import type { ResolvedState } from '../request-state-resolver'
import type { GuidanceCall, GuidanceNotice } from './engine'
import type { GuidanceProductState } from './product-state'
import { MCP_GUIDANCE_INBOX_REPORT_MATCH_FLAG } from './rules'
import { callerCacheIdentity, isSelfDrivingAudience } from './self-driving-activation'

const RULE_ID = 'error-tracking-inbox-report-match'
const ISSUE_TOOL = 'query-error-tracking-issue'
const RETRIEVE_TOOL = 'inbox-reports-retrieve'
const SESSION_TTL_SECONDS = 24 * 60 * 60
const CALLER_TTL_SECONDS = 30 * 60
const LOOKUP_TTL_SECONDS = 5 * 60
const REPORT_LIMIT = 5
const TITLE_MAX_LENGTH = 120
const OPEN_STATUSES = ['ready', 'pending_input', 'in_progress', 'monitoring']
const CLOSED_STATUSES = ['resolved', 'closed']

const reportListSchema = z.object({
    results: z.array(
        z.object({
            id: z.string(),
            title: z.string().nullable(),
            status: z.string(),
            work_state: z.string(),
            suppression_source: z.string().nullable(),
            pull_requests: z.array(z.object({ state: z.string() })),
        })
    ),
})
type InboxReport = z.infer<typeof reportListSchema>['results'][number]

// Only `dismissed` is a person's decision. The other suppression sources are judge verdicts that nobody reviewed.
function isClosedByTeam(report: InboxReport): boolean {
    return (
        CLOSED_STATUSES.includes(report.status) ||
        (report.status === 'suppressed' && report.suppression_source === 'dismissed')
    )
}

// The safety judge holds back a report whose content tries to manipulate an agent, so the notice never names one.
function pickReport(reports: InboxReport[]): InboxReport | undefined {
    const safe = reports.filter((report) => report.suppression_source !== 'safety_judge')
    return safe.find((report) => OPEN_STATUSES.includes(report.status)) ?? safe.find(isClosedByTeam)
}

function reportMatchText(state: ResolvedState, report: InboxReport): string {
    const title = (report.title ?? '').replace(/\s+/g, ' ').trim()
    const input = JSON.stringify({ id: report.id })
    return formatPrompt(REPORT_MATCH_PROMPT, {
        closed_note: isClosedByTeam(report) ? CLOSED_NOTE.trim() : '',
        status: report.status,
        work_state: report.work_state,
        open_pull_request: report.pull_requests.some(({ state }) => state === 'open' || state === 'draft')
            ? 'yes'
            : 'no',
        retrieve_call: state.useSingleExec
            ? `\`call ${RETRIEVE_TOOL} ${input}\``
            : `the \`${RETRIEVE_TOOL}\` tool and \`${input}\``,
        // Last, because `formatPrompt` fills the placeholders in order and would fill one that the title contains.
        report_title: JSON.stringify(
            title.length > TITLE_MAX_LENGTH ? `${title.slice(0, TITLE_MAX_LENGTH - 1)}…` : title
        ),
    }).replace(/\n+/g, '\n')
}

function shownKey(state: ResolvedState, handle: string, issueId: string): string {
    const identity = createHash('sha256')
        .update(`${state.distinctId}|${handle}|${issueId}`)
        .digest('base64url')
        .slice(0, 22)
    return `mcp:guidance:inbox-report-match:shown:{${identity}}`
}

async function findReport(
    redis: RedisLike,
    state: ResolvedState,
    projectId: string,
    issueId: string
): Promise<InboxReport | undefined> {
    const key = `mcp:guidance:inbox-report-match:lookup:{${callerCacheIdentity(state, projectId, issueId)}}`
    const cached = await redis.get(key)
    if (cached !== null) {
        return pickReport(reportListSchema.parse(JSON.parse(cached)).results)
    }
    let report: InboxReport | undefined
    // A failed lookup is remembered as a miss too, so a loop over one issue does not call the API every time.
    try {
        const list = reportListSchema.parse(
            await state.context.api.request<Schemas.PaginatedSignalReportListList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(projectId)}/signals/reports/`,
                query: {
                    source_product: 'error_tracking',
                    source_id: issueId,
                    include_all_statuses: true,
                    ordering: '-updated_at',
                    include_source_metadata: false,
                    limit: REPORT_LIMIT,
                },
                signal: AbortSignal.timeout(1000),
            })
        )
        report = pickReport(list.results)
    } finally {
        await redis.set(key, JSON.stringify({ results: report ? [report] : [] }), 'EX', LOOKUP_TTL_SECONDS)
    }
    return report
}

// Scoped like the activation notice: a call without a carried handle counts under the caller, and also marks the
// handle that the client can echo later, so the notice does not repeat in that session.
async function lookupReportMatch(
    redis: RedisLike,
    state: ResolvedState,
    productState: GuidanceProductState,
    firstSessionCall: boolean,
    issueId: string
): Promise<GuidanceNotice | undefined> {
    const suppliedHandle = firstSessionCall ? undefined : state.carriedContextSessionKey
    const countingKey = shownKey(state, suppliedHandle ?? '', issueId)
    const ttl = suppliedHandle ? SESSION_TTL_SECONDS : CALLER_TTL_SECONDS
    if (await redis.get(countingKey)) {
        await redis.expire(countingKey, ttl)
        return undefined
    }
    const projectId = String(await state.context.stateManager.getProjectId())
    const report = await findReport(redis, state, projectId, issueId)
    if (!report || !productState.hasBudgetLeft()) {
        return undefined
    }
    if ((await redis.set(countingKey, '1', 'EX', ttl, 'NX')) !== 'OK') {
        return undefined
    }
    const ownedKeys = [countingKey]
    let keepReservation = false
    try {
        const handleToMirror = firstSessionCall
            ? state.carriedContextSessionKey
            : state.requestContext.mcpConversationId
        if (!suppliedHandle && handleToMirror) {
            const mirrorKey = shownKey(state, handleToMirror, issueId)
            if ((await redis.set(mirrorKey, '1', 'EX', SESSION_TTL_SECONDS, 'NX')) !== 'OK') {
                return undefined
            }
            ownedKeys.push(mirrorKey)
        }
        if (!productState.hasBudgetLeft()) {
            return undefined
        }
        keepReservation = true
        return { ruleId: RULE_ID, outcome: 'shown', text: reportMatchText(state, report) }
    } finally {
        if (!keepReservation) {
            await Promise.all(ownedKeys.map((key) => redis.del(key).catch(() => undefined)))
        }
    }
}

export async function inboxReportMatchGuidance(
    redis: RedisLike,
    state: ResolvedState,
    call: GuidanceCall,
    productState: GuidanceProductState,
    firstSessionCall: boolean
): Promise<GuidanceNotice | undefined> {
    const issueId = call.args?.issueId
    if (
        call.toolName !== ISSUE_TOOL ||
        typeof issueId !== 'string' ||
        call.isError ||
        state.toolFeatureFlags?.[MCP_GUIDANCE_INBOX_REPORT_MATCH_FLAG] !== true ||
        !isSelfDrivingAudience(state) ||
        !state.allTools.some((tool) => tool.name === RETRIEVE_TOOL)
    ) {
        return undefined
    }
    return productState.withinBudget('inbox_report_match', () =>
        lookupReportMatch(redis, state, productState, firstSessionCall, issueId)
    )
}
