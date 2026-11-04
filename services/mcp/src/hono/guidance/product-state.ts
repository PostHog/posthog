import { z } from 'zod'

import type { RedisLike } from '../cache/RedisCache'
import { guidanceProductStateLookupsTotal } from '../metrics'
import type { ResolvedState } from '../request-state-resolver'

// The tool result waits for guidance, so all lookups of one evaluation share this budget.
const LOOKUP_BUDGET_MS = 300
// A lookup that misses the budget keeps running so that it can fill the cache for the next call.
const BACKGROUND_TIMEOUT_MS = 5_000
const HAS_ISSUES_TTL_SECONDS = 24 * 60 * 60
// Short, because the answer changes when a project sends its first exception.
const NO_ISSUES_TTL_SECONDS = 10 * 60

const issuesExistSchema = z.object({ exists: z.boolean() })

// Every read returns `undefined` when the answer is unknown, so a failure never fails the tool call.
export class GuidanceProductState {
    private deadlineAt: number | undefined
    private ingestedData: Promise<boolean | undefined> | undefined
    private errorTrackingIssues: Promise<boolean | undefined> | undefined

    constructor(
        private readonly redis: RedisLike,
        private readonly state: ResolvedState
    ) {}

    hasIngestedData(): Promise<boolean | undefined> {
        this.ingestedData ??= this.withinBudget('ingested_data', () => this.readIngestedData())
        return this.ingestedData
    }

    // The cached answer is per project, so a rule must trigger only on a tool that needs `error_tracking:read`.
    hasErrorTrackingIssues(): Promise<boolean | undefined> {
        this.errorTrackingIssues ??= this.withinBudget('error_tracking_issues', () => this.readErrorTrackingIssues())
        return this.errorTrackingIssues
    }

    private async readIngestedData(): Promise<boolean | undefined> {
        const project = await this.state.context.stateManager.getCachedOrFetchProject()
        return project?.ingested_event
    }

    private async readErrorTrackingIssues(): Promise<boolean> {
        const projectId = await this.state.context.stateManager.getProjectId()
        const key = `mcp:guidance:state:error-tracking-issues:${projectId}`
        const cached = await this.redis.get(key)
        if (cached !== null) {
            return cached === '1'
        }
        const { exists } = issuesExistSchema.parse(
            await this.state.context.api.request<unknown>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(projectId)}/error_tracking/issues/exists/`,
                timeoutMs: BACKGROUND_TIMEOUT_MS,
                signal: AbortSignal.timeout(BACKGROUND_TIMEOUT_MS),
            })
        )
        const ttl = exists ? HAS_ISSUES_TTL_SECONDS : NO_ISSUES_TTL_SECONDS
        await this.redis.set(key, exists ? '1' : '0', 'EX', ttl).catch(() => undefined)
        return exists
    }

    async withinBudget<T>(check: string, read: () => Promise<T>): Promise<T | undefined> {
        this.deadlineAt ??= Date.now() + LOOKUP_BUDGET_MS
        const work = read()
        // After a timeout nothing awaits this promise, so its rejection needs its own handler.
        work.catch(() => undefined)
        let timer: ReturnType<typeof setTimeout> | undefined
        const timedOut = new Promise<'timeout'>((resolve) => {
            timer = setTimeout(() => resolve('timeout'), Math.max(0, this.deadlineAt! - Date.now()))
        })
        try {
            const outcome = await Promise.race([work.then((value) => ({ value })), timedOut])
            guidanceProductStateLookupsTotal.inc({ check, result: outcome === 'timeout' ? 'timeout' : 'answered' })
            return outcome === 'timeout' ? undefined : outcome.value
        } catch {
            guidanceProductStateLookupsTotal.inc({ check, result: 'error' })
            return undefined
        } finally {
            clearTimeout(timer)
        }
    }
}
