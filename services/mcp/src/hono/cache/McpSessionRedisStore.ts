import { createHash } from 'node:crypto'

import { hash } from '@/lib/utils'

import type { MCPClientContext } from '../mcp-context'
import { sessionCacheComparisonsTotal, sessionCacheOperationsTotal } from '../metrics'
import type { RedisLike } from './RedisCache'

const LEGACY_TTL_SECONDS = 7 * 24 * 60 * 60
const COMPACT_IDLE_TTL_SECONDS = 24 * 60 * 60
const SESSION_CONTEXT_KEYS = [
    'mcpClientName',
    'mcpClientVersion',
    'mcpProtocolVersion',
    'mcpConsumer',
    'mcpVendorClient',
] as const

type SessionContextKey = (typeof SESSION_CONTEXT_KEYS)[number]
type SessionContext = Pick<MCPClientContext, SessionContextKey>
type RedisWithEval = RedisLike & {
    eval(script: string, numberOfKeys: number, ...args: string[]): Promise<unknown>
}

const MERGE_COMPACT_CONTEXT_SCRIPT = `
local currentRaw = redis.call('GET', KEYS[1])
local current = currentRaw and cjson.decode(currentRaw) or {}
local cached = ARGV[1] ~= '' and cjson.decode(ARGV[1]) or nil
local desired = cjson.decode(ARGV[2])

for key, value in pairs(desired) do
    if current[key] == nil or (cached ~= nil and current[key] == cached[key]) then
        current[key] = value
    end
end

redis.call('SET', KEYS[1], cjson.encode(current), 'EX', ARGV[3])
return 1
`

export class McpSessionRedisStore {
    private readonly legacyPrefix: string
    private readonly compactKey: string

    constructor(
        private readonly redis: RedisLike,
        sessionId: string
    ) {
        this.legacyPrefix = `mcp:session:${hash(sessionId)}`
        const digest = createHash('sha256').update(sessionId).digest()
        this.compactKey = `mcp:s:${digest.subarray(0, 16).toString('base64url')}:c`
    }

    async resolve(liveContext: MCPClientContext, projectId: string | undefined): Promise<SessionContext> {
        const [legacyContext, compactContext] = await Promise.all([this.readLegacy(), this.readCompact()])
        this.recordComparison(legacyContext, compactContext)

        const readCompact = shouldReadCompact(projectId)
        const storedContext = readCompact && compactContext ? compactContext : legacyContext
        const resolvedContext = mergeContexts(storedContext, liveContext)

        await Promise.all([
            this.writeMissingLegacyValues(legacyContext, liveContext),
            this.refreshCompact(resolvedContext, compactContext),
        ])

        sessionCacheOperationsTotal.inc({ schema: readCompact ? 'compact' : 'legacy', operation: 'read' })
        return resolvedContext
    }

    private async readLegacy(): Promise<Partial<SessionContext>> {
        const entries = await Promise.all(
            SESSION_CONTEXT_KEYS.map(async (key) => {
                const raw = await this.redis.get(`${this.legacyPrefix}:${key}`)
                return [key, raw === null ? undefined : (JSON.parse(raw) as string)] as const
            })
        )
        return Object.fromEntries(entries)
    }

    private async readCompact(): Promise<SessionContext | null> {
        try {
            const raw = await this.redis.get(this.compactKey)
            return raw === null ? null : (JSON.parse(raw) as SessionContext)
        } catch {
            sessionCacheOperationsTotal.inc({ schema: 'compact', operation: 'read_error' })
            return null
        }
    }

    private async writeMissingLegacyValues(
        cached: Partial<SessionContext>,
        liveContext: MCPClientContext
    ): Promise<void> {
        await Promise.all(
            SESSION_CONTEXT_KEYS.flatMap((key) => {
                const value = liveContext[key]
                if (cached[key] !== undefined || value === undefined) {
                    return []
                }
                return [this.redis.set(`${this.legacyPrefix}:${key}`, JSON.stringify(value), 'EX', LEGACY_TTL_SECONDS)]
            })
        )
    }

    private async refreshCompact(context: SessionContext, cached: SessionContext | null): Promise<void> {
        try {
            if (cached !== null && contextsEqual(context, cached)) {
                await this.redis.expire(this.compactKey, COMPACT_IDLE_TTL_SECONDS)
                sessionCacheOperationsTotal.inc({ schema: 'compact', operation: 'refresh' })
            } else {
                await (this.redis as RedisWithEval).eval(
                    MERGE_COMPACT_CONTEXT_SCRIPT,
                    1,
                    this.compactKey,
                    cached === null ? '' : JSON.stringify(cached),
                    JSON.stringify(context),
                    String(COMPACT_IDLE_TTL_SECONDS)
                )
                sessionCacheOperationsTotal.inc({ schema: 'compact', operation: 'write' })
            }
        } catch {
            sessionCacheOperationsTotal.inc({ schema: 'compact', operation: 'write_error' })
        }
    }

    private recordComparison(legacy: Partial<SessionContext>, compact: SessionContext | null): void {
        if (compact === null) {
            sessionCacheComparisonsTotal.inc({ result: 'compact_missing' })
            return
        }
        sessionCacheComparisonsTotal.inc({ result: contextsEqual(legacy, compact) ? 'match' : 'mismatch' })
    }
}

function mergeContexts(stored: Partial<SessionContext>, live: MCPClientContext): SessionContext {
    return Object.fromEntries(SESSION_CONTEXT_KEYS.map((key) => [key, stored[key] ?? live[key]])) as SessionContext
}

function contextsEqual(left: Partial<SessionContext>, right: SessionContext): boolean {
    return SESSION_CONTEXT_KEYS.every((key) => left[key] === right[key])
}

function shouldReadCompact(projectId: string | undefined): boolean {
    if (process.env.MCP_SESSION_CACHE_V2_READ_ALL === 'true') {
        return true
    }
    if (!projectId) {
        return false
    }
    const projects = new Set(
        (process.env.MCP_SESSION_CACHE_V2_READ_PROJECT_IDS ?? '')
            .split(',')
            .map((value) => value.trim())
            .filter(Boolean)
    )
    return projects.has(projectId)
}
