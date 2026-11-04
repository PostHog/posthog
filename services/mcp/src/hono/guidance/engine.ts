import { createHash } from 'node:crypto'

import { resolveScopePreset } from '@/lib/scope-preset'

import type { RedisLike } from '../cache/RedisCache'
import { resolveSessionKey } from '../mcp-context'
import { guidanceEvaluationErrorsTotal, guidanceNoticesTotal } from '../metrics'
import type { ResolvedState } from '../request-state-resolver'
import { GuidanceProductState } from './product-state'
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
    resultEmpty?: boolean | undefined
}

export type GuidanceOutcome = 'shown' | 'flag_off' | 'suppressed' | 'no_consent'

export interface GuidanceNotice {
    ruleId: string
    outcome: GuidanceOutcome
    /** Only present when the notice is shown to the agent. */
    text?: string
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

function isSet(value: unknown): boolean {
    return value !== undefined && value !== null && value !== ''
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
    if (trigger.resultEmpty !== undefined && trigger.resultEmpty !== (call.resultEmpty === true)) {
        return false
    }
    if (trigger.excludeArgs?.some((path) => isSet(readArgPath(call.args, path)))) {
        return false
    }
    if (trigger.argPattern !== undefined) {
        const value = trigger.argPath === undefined ? call.args : readArgPath(call.args, trigger.argPath)
        const text = typeof value === 'string' ? value : value === undefined ? '' : JSON.stringify(value)
        if (trigger.argMaxLength !== undefined && text.length > trigger.argMaxLength) {
            return false
        }
        return trigger.argPattern.test(text)
    }
    return true
}

// Server-minted tokens are not excluded here: scouts carry the same internal scopes as sandbox
// runs, so each rule's `presets` decides which of them it reaches.
function isGuidanceAudience(state: ResolvedState): boolean {
    return !(state.isImpersonated || state.suppressAnalytics || state.clientProfile.consumer === 'posthog_ai')
}

// The flag and org consent decide only whether the text goes out: an eligible caller with the
// flag off, or without AI consent, is counted the same way, so the stamped outcome gives a
// control group and a measure of how often consent blocks the notice.
function ruleApplies(rule: GuidanceRule, state: ResolvedState, preset: string): boolean {
    // The roster drops consent-gated tools without org consent, so it cannot decide these callers.
    const withheldForConsent = rule.requiresAiConsent === true && state.aiConsentGiven !== true
    return (
        rule.trigger.presets.includes(preset as GuidanceRule['trigger']['presets'][number]) &&
        (withheldForConsent || rule.requiresTool.every((name) => state.allTools.some((tool) => tool.name === name)))
    )
}

// One script per rule, so a concurrent batch cannot reserve the same notice twice. The shown
// key counts reports of either kind, so a suppressed outcome that loses the call to another
// rule stays pending and is reported on the next matching call instead of being dropped.
const RULE_STATE_SCRIPT = `
local ttl = tonumber(ARGV[1])
if ARGV[4] == 'touch' then
    redis.call('EXPIRE', KEYS[1], ttl)
    redis.call('EXPIRE', KEYS[2], ttl)
    redis.call('EXPIRE', KEYS[3], ttl)
    return tonumber(redis.call('GET', KEYS[3]) or 0)
end
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
if ARGV[5] ~= '1' or matched < tonumber(ARGV[2]) then
    return 0
end
local shown = redis.call('INCR', KEYS[3])
redis.call('EXPIRE', KEYS[3], ttl)
if shown > tonumber(ARGV[3]) then
    return 0
end
if redis.call('EXISTS', KEYS[2]) == 1 then
    return 2
end
return 1
`

enum RuleResult {
    None = 0,
    Fired = 1,
    Suppressed = 2,
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
        try {
            const sessionKey = await this.resolveCountingKey(state)
            const ttl = sessionKey ? SESSION_TTL_SECONDS : CALLER_TTL_SECONDS
            // The braces are a cluster hash tag, so the script can touch a rule's three keys together.
            const scope = `mcp:guidance:{${hashKey(`${state.distinctId}|${sessionKey ?? ''}`)}}`
            const productState = new GuidanceProductState(this.redis, state)
            let winner: GuidanceNotice | undefined
            for (const rule of rules) {
                const result = await this.touchRule(rule, scope, ttl, call, winner === undefined, productState)
                if (result === RuleResult.Fired) {
                    const outcome = firedOutcome(rule, state)
                    winner = {
                        ruleId: rule.id,
                        outcome,
                        ...(outcome === 'shown'
                            ? { text: typeof rule.text === 'string' ? rule.text : rule.text(call) }
                            : {}),
                    }
                } else if (result === RuleResult.Suppressed && !winner) {
                    winner = { ruleId: rule.id, outcome: 'suppressed' }
                }
            }
            if (winner) {
                guidanceNoticesTotal.inc({ rule: winner.ruleId, outcome: winner.outcome })
            }
            return winner
        } catch (error) {
            guidanceEvaluationErrorsTotal.inc()
            console.warn('[Guidance] evaluation failed:', error instanceof Error ? error.message : String(error))
            return undefined
        }
    }

    // A call that carries no handle counts under the caller, because the SDK mints a handle on
    // every such call and a client that never echoes one would otherwise never reach a threshold.
    // The minted handle is aliased to the caller, so a client that does echo it keeps the counters
    // and suppression the conversation started with instead of restarting under the handle.
    private async resolveCountingKey(state: ResolvedState): Promise<string | undefined> {
        const handle = resolveSessionKey(state.requestContext)
        if (!handle) {
            return undefined
        }
        const aliasKey = `mcp:guidance:alias:{${hashKey(`${state.distinctId}|${handle}`)}}`
        if (state.carriedContextHandle === false) {
            await this.redis.set(aliasKey, '1', 'EX', SESSION_TTL_SECONDS)
            return undefined
        }
        return (await this.redis.get(aliasKey)) === '1' ? undefined : handle
    }

    private async touchRule(
        rule: GuidanceRule,
        scope: string,
        ttl: number,
        call: GuidanceCall,
        canFire: boolean,
        productState: GuidanceProductState
    ): Promise<RuleResult> {
        const suppressing = rule.suppressIfCalled.some((pattern) => matchesToolPattern(pattern, call.toolName))
        if (!suppressing && !triggerMatches(rule, call)) {
            return RuleResult.None
        }
        const key = (suffix: string): string => `${scope}:${rule.id}:${suffix}`
        const runScript = (mode: 'touch' | 'suppress' | 'match'): Promise<unknown> =>
            this.redis.eval(
                RULE_STATE_SCRIPT,
                3,
                key('matched'),
                key('suppressed'),
                key('shown'),
                ttl,
                rule.threshold,
                rule.maxPerSession,
                mode,
                canFire ? '1' : '0'
            )
        const { condition } = rule
        if (suppressing || !condition) {
            return Number(await runScript(suppressing ? 'suppress' : 'match')) as RuleResult
        }
        // `touch` keeps a capped rule's counters alive without the `match` count, so a rejected call
        // spends no `maxPerSession`. The budget covers every step because the tool result waits here.
        const result = await productState.withinBudget('rule_gate', async () => {
            const shown = Number(await runScript('touch'))
            if (shown >= rule.maxPerSession || !(await condition({ call, productState }))) {
                return RuleResult.None
            }
            return Number(await runScript('match')) as RuleResult
        })
        return result ?? RuleResult.None
    }
}

function firedOutcome(rule: GuidanceRule, state: ResolvedState): GuidanceOutcome {
    if (rule.requiresAiConsent && state.aiConsentGiven !== true) {
        return 'no_consent'
    }
    return state.toolFeatureFlags?.[rule.flag] === true ? 'shown' : 'flag_off'
}

function hashKey(value: string): string {
    return createHash('sha256').update(value).digest('base64url').slice(0, 22)
}

// Attached on errors too: a notice that fires on repeated failures must reach the agent. A JSON
// call keeps its result as the first block, because callers parse `content[0]` as raw JSON.
export function attachGuidanceNotice(
    result: unknown,
    notice: GuidanceNotice | undefined,
    options: { jsonOutput?: boolean } = {}
): unknown {
    if (
        !notice?.text ||
        typeof result !== 'object' ||
        result === null ||
        !Array.isArray((result as { content?: unknown }).content)
    ) {
        return result
    }
    const withContent = result as { content: unknown[] }
    const block = { type: 'text', text: notice.text }
    return {
        ...withContent,
        content: options.jsonOutput ? [...withContent.content, block] : [block, ...withContent.content],
    }
}

export function guidanceAnalyticsProperties(notice: GuidanceNotice | undefined): Record<string, unknown> {
    return notice ? { mcp_guidance_rule: notice.ruleId, mcp_guidance_outcome: notice.outcome } : {}
}
