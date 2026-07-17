import type { RequestContext } from '@/hono/request-context'
import type { SkillsSessionState } from '@/tools/exec'

/**
 * Session-scoped skill-usage markers for the exec skills-first nudge, backed by
 * the same Redis session cache that stores MCP client context. Requires an MCP
 * session id — stateless clients get no nudge rather than a per-request one.
 */
export function buildSkillsSessionState(
    reqCtx: RequestContext,
    mcpSessionId: string | undefined
): SkillsSessionState | undefined {
    if (!mcpSessionId) {
        return undefined
    }
    const cache = reqCtx.sessionCache
    return {
        async hasLearned(): Promise<boolean> {
            return (await cache.get('skillsLearnedAt')) !== undefined
        },
        async markLearned(): Promise<void> {
            await cache.set('skillsLearnedAt', Date.now())
        },
        async claimNudge(): Promise<boolean> {
            if ((await cache.get('skillsNudgedAt')) !== undefined) {
                return false
            }
            await cache.set('skillsNudgedAt', Date.now())
            return true
        },
    }
}
