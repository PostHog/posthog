import { createHash } from 'node:crypto'

import { resolveScopePreset } from '@/lib/scope-preset'

import type { RedisLike } from '../cache/RedisCache'
import { resolveSessionKey } from '../mcp-context'
import { guidanceNoticesTotal } from '../metrics'
import type { ResolvedState } from '../request-state-resolver'
import { GUIDANCE_RULES, type GuidanceRule } from './rules'

// A conversation handle outlives any single request, so its counters keep the session store's
// idle TTL. Without a handle the counters key on the caller and expire like a 30-minute idle
// session, which is the same sessionization the analytics queries fall back to.
const SESSION_TTL_SECONDS = 24 * 60 * 60
const CALLER_TTL_SECONDS = 30 * 60

export interface GuidanceCall {
    /** The effective tool name: the inner tool for an exec `call`, `exec` for other verbs. */
    toolName: string
    execVerb?: string | undefined
    args: Record<string, unknown> | undefined
    isError: boolean
}

export interface GuidanceNotice {
    ruleId: string
    text: string
}

export function matchesToolPattern(pattern: string, toolName: string): boolean {
    return pattern.endsWith('*') ? toolName.startsWith(pattern.slice(0, -1)) : pattern === toolName
}

function readArgPath(args: Record<string, unknown> | undefined, path: string): unknown {
    return path.split('.').reduce<unknown>((current, segment) => {
        if (typeof current !== 'object' || current === null) {
            return undefined
        }
        return (current as Record<string, unknown>)[segment]
    }, args)
}

export function triggerMatches(rule: GuidanceRule, call: GuidanceCall): boolean {
    const { trigger } = rule
    if (trigger.tool !== undefined && !matchesToolPattern(trigger.tool, call.toolName)) {
        return false
    }
    if (trigger.execVerb !== undefined && trigger.execVerb !== call.execVerb) {
        return false
    }
    if (trigger.outcome === 'success' && call.isError) {
        return false
    }
    if (trigger.outcome === 'error' && !call.isError) {
        return false
    }
    if (trigger.argPattern !== undefined) {
        const value = trigger.argPath === undefined ? call.args : readArgPath(call.args, trigger.argPath)
        const text = typeof value === 'string' ? value : value === undefined ? '' : JSON.stringify(value)
        return trigger.argPattern.test(text)
    }
    return true
}

// Mirrors the no-data notice audience: the people who set up and drive the agent themselves.
function isGuidanceAudience(state: ResolvedState): boolean {
    return !(
        state.isImpersonated ||
        state.suppressAnalytics ||
        state.apiKeyScopes.includes('internal_run:read') ||
        state.clientProfile.consumer === 'posthog_ai'
    )
}

function ruleApplies(rule: GuidanceRule, state: ResolvedState, preset: string): boolean {
    return (
        state.toolFeatureFlags?.[rule.flag] === true &&
        rule.trigger.presets.includes(preset as GuidanceRule['trigger']['presets'][number]) &&
        rule.requiresTool.some((name) => state.allTools.some((tool) => tool.name === name))
    )
}

export class GuidanceEngine {
    constructor(
        private readonly redis: RedisLike,
        private readonly rules: readonly GuidanceRule[] = GUIDANCE_RULES
    ) {}

    // Never throws: a Redis problem silently yields no notice, so `tools/call` keeps working.
    async evaluate(state: ResolvedState, call: GuidanceCall): Promise<GuidanceNotice | undefined> {
        if (!isGuidanceAudience(state)) {
            return undefined
        }
        const preset = resolveScopePreset(state.apiKeyScopes)
        const rules = this.rules.filter((rule) => ruleApplies(rule, state, preset))
        if (rules.length === 0) {
            return undefined
        }
        const sessionKey = resolveSessionKey(state.requestContext)
        const ttl = sessionKey ? SESSION_TTL_SECONDS : CALLER_TTL_SECONDS
        const scope = `mcp:guidance:${hashKey(sessionKey ?? `caller:${state.distinctId}`)}`

        try {
            const candidates = await Promise.all(rules.map((rule) => this.evaluateRule(rule, scope, ttl, call)))
            const winner = candidates.find((candidate) => candidate !== undefined)
            if (!winner) {
                return undefined
            }
            await this.recordShown(winner.id, scope, ttl)
            guidanceNoticesTotal.inc({ rule: winner.id })
            return { ruleId: winner.id, text: winner.text }
        } catch {
            return undefined
        }
    }

    private async evaluateRule(
        rule: GuidanceRule,
        scope: string,
        ttl: number,
        call: GuidanceCall
    ): Promise<GuidanceRule | undefined> {
        const key = (suffix: string): string => `${scope}:${rule.id}:${suffix}`
        if (rule.suppressIfCalled.some((pattern) => matchesToolPattern(pattern, call.toolName))) {
            await this.redis.set(key('suppressed'), '1', 'EX', ttl)
            return undefined
        }
        if (!triggerMatches(rule, call)) {
            return undefined
        }
        const [matched, suppressed, shown] = await Promise.all([
            this.redis.incr(key('matched')),
            this.redis.get(key('suppressed')),
            this.redis.get(key('shown')),
        ])
        await this.redis.expire(key('matched'), ttl)
        if (suppressed !== null || matched < rule.threshold || Number(shown ?? 0) >= rule.maxPerSession) {
            return undefined
        }
        return rule
    }

    private async recordShown(ruleId: string, scope: string, ttl: number): Promise<void> {
        const key = `${scope}:${ruleId}:shown`
        await this.redis.incr(key)
        await this.redis.expire(key, ttl)
    }
}

function hashKey(value: string): string {
    return createHash('sha256').update(value).digest('base64url').slice(0, 22)
}

// Prepended on errors too: a notice that fires on repeated failures must reach the agent.
export function prependGuidanceNotice(result: unknown, notice: GuidanceNotice | undefined): unknown {
    if (
        !notice ||
        typeof result !== 'object' ||
        result === null ||
        !Array.isArray((result as { content?: unknown }).content)
    ) {
        return result
    }
    const withContent = result as { content: unknown[] }
    return { ...withContent, content: [{ type: 'text', text: notice.text }, ...withContent.content] }
}

export function guidanceAnalyticsProperties(notice: GuidanceNotice | undefined): Record<string, unknown> {
    return notice ? { mcp_guidance_rule: notice.ruleId } : {}
}
