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

// One script per rule, so a concurrent batch cannot reserve the same notice twice.
const RULE_STATE_SCRIPT = `
local ttl = tonumber(ARGV[1])
if ARGV[4] == 'suppress' then
    redis.call('SET', KEYS[2], '1', 'EX', ttl)
    redis.call('EXPIRE', KEYS[1], ttl)
    redis.call('EXPIRE', KEYS[3], ttl)
    return 0
end
local matched = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('EXPIRE', KEYS[2], ttl)
redis.call('EXPIRE', KEYS[3], ttl)
if ARGV[5] ~= '1' or matched < tonumber(ARGV[2]) or redis.call('EXISTS', KEYS[2]) == 1 then
    return 0
end
local shown = redis.call('INCR', KEYS[3])
redis.call('EXPIRE', KEYS[3], ttl)
if shown > tonumber(ARGV[3]) then
    return 0
end
return 1
`

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
        // The braces are a cluster hash tag, so the script can touch a rule's three keys together.
        const scope = `mcp:guidance:{${hashKey(`${state.distinctId}|${sessionKey ?? ''}`)}}`

        try {
            let winner: GuidanceRule | undefined
            for (const rule of rules) {
                if (await this.touchRule(rule, scope, ttl, call, winner === undefined)) {
                    winner = rule
                }
            }
            if (!winner) {
                return undefined
            }
            guidanceNoticesTotal.inc({ rule: winner.id })
            return { ruleId: winner.id, text: winner.text }
        } catch {
            return undefined
        }
    }

    private async touchRule(
        rule: GuidanceRule,
        scope: string,
        ttl: number,
        call: GuidanceCall,
        canFire: boolean
    ): Promise<boolean> {
        const suppressing = rule.suppressIfCalled.some((pattern) => matchesToolPattern(pattern, call.toolName))
        if (!suppressing && !triggerMatches(rule, call)) {
            return false
        }
        const key = (suffix: string): string => `${scope}:${rule.id}:${suffix}`
        const fired = await this.redis.eval(
            RULE_STATE_SCRIPT,
            3,
            key('matched'),
            key('suppressed'),
            key('shown'),
            ttl,
            rule.threshold,
            rule.maxPerSession,
            suppressing ? 'suppress' : 'match',
            canFire ? '1' : '0'
        )
        return Number(fired) === 1
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
