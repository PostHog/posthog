import type { RequestProperties } from '@/lib/request-properties'
import { redactToken } from '@/lib/utils'
import type { State } from '@/tools/types'

import { trackRateLimited } from './analytics'
import { RedisCache, type RedisLike } from './cache/RedisCache'
import { rateLimitBlockedByTeam } from './metrics'
import type { RateLimitResult, RequestCharge } from './rate-limiter'

const UNRESOLVED_TEAM = 'unresolved'
const OVERFLOW_TEAM = 'other'

// team_id ultimately derives from the client-controlled x-posthog-project-id
// header, and this runs on the blocked path — so an attacker past the limit
// could otherwise mint an unbounded number of label series and exhaust the heap.
// Only accept a plausible numeric project id, and hard-cap distinct values.
const VALID_TEAM_ID = /^\d{1,19}$/
const MAX_TRACKED_TEAMS = 1000
const trackedTeamIds = new Set<string>()

function isPlausibleTeamId(teamId: string | undefined): teamId is string {
    return !!teamId && VALID_TEAM_ID.test(teamId)
}

function normalizeTeamId(teamId: string | undefined): string {
    if (!isPlausibleTeamId(teamId)) {
        return UNRESOLVED_TEAM
    }
    if (trackedTeamIds.has(teamId)) {
        return teamId
    }
    if (trackedTeamIds.size >= MAX_TRACKED_TEAMS) {
        return OVERFLOW_TEAM
    }
    trackedTeamIds.add(teamId)
    return teamId
}

export async function recordRateLimitBlock(
    redis: RedisLike,
    props: RequestProperties,
    result: RateLimitResult,
    charge: RequestCharge
): Promise<void> {
    let teamId = props.projectId
    if (!teamId) {
        try {
            teamId = (await new RedisCache<State>(props.userHash, redis, 'token').get('projectId')) ?? undefined
        } catch {
            // best-effort identity
        }
    }
    rateLimitBlockedByTeam.inc({ scope: result.scope, team_id: normalizeTeamId(teamId) })

    trackRateLimited(props, {
        scope: result.scope,
        limit: result.limit,
        resetSeconds: result.resetSeconds,
        charge,
        ...(isPlausibleTeamId(teamId) ? { projectId: teamId } : {}),
    })

    // Log so we can trace which token is hitting the limit; the token is redacted
    // to its last 4 chars so the line is useless to anyone who shouldn't have it.
    console.warn(
        '[RateLimiter] rate limited',
        JSON.stringify({ scope: result.scope, projectId: teamId ?? null, token: redactToken(props.apiToken) })
    )
}

// test-only: reset the process-lifetime cardinality cap between cases
export function __resetTrackedTeamIds(): void {
    trackedTeamIds.clear()
}
