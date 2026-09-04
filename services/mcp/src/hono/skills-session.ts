import type { RequestContext } from '@/hono/request-context'
import type { SkillsSessionState } from '@/tools/exec'

/**
 * Session-scoped skill-usage markers for the exec skills-first gate, backed by
 * a Redis cache keyed on the MCP session id. Requires that id — stateless
 * clients get no gate rather than a per-request one.
 */
export function buildSkillsSessionState(
    reqCtx: RequestContext,
    mcpSessionId: string | undefined
): SkillsSessionState | undefined {
    if (!mcpSessionId) {
        return undefined
    }
    const cache = reqCtx.getSessionCache(mcpSessionId)
    return {
        async hasLearned(): Promise<boolean> {
            return (await cache.get('skillsLearnedAt')) !== undefined
        },
        async markLearned(): Promise<void> {
            await cache.set('skillsLearnedAt', Date.now())
        },
        async hasAcknowledgedNoSkills(): Promise<boolean> {
            return (await cache.get('skillsNoSkillsAckAt')) !== undefined
        },
        async markAcknowledgedNoSkills(): Promise<void> {
            await cache.set('skillsNoSkillsAckAt', Date.now())
        },
    }
}
