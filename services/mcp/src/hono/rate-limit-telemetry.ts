import type { RequestProperties } from '@/lib/request-properties'
import type { State } from '@/tools/types'

import { RedisCache, type RedisLike } from './cache/RedisCache'
import { rateLimitBlockedByTeam } from './metrics'
import type { RateLimitResult } from './rate-limiter'

const UNRESOLVED_TEAM = 'unresolved'

export async function recordRateLimitBlock(
    redis: RedisLike,
    props: RequestProperties,
    result: RateLimitResult
): Promise<void> {
    let teamId = props.projectId
    if (!teamId) {
        try {
            teamId = (await new RedisCache<State>(props.userHash, redis, 'token').get('projectId')) ?? undefined
        } catch {
            // best-effort identity
        }
    }
    rateLimitBlockedByTeam.inc({ scope: result.scope, team_id: teamId ?? UNRESOLVED_TEAM })
}
