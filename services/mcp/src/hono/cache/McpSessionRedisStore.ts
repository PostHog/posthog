import { createHash } from 'node:crypto'

import type { MCPClientContext } from '../mcp-context'
import { sessionCacheOperationsTotal } from '../metrics'
import type { RedisLike } from './RedisCache'

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
    private readonly compactKey: string

    constructor(
        private readonly redis: RedisLike,
        sessionId: string
    ) {
        const digest = createHash('sha256').update(sessionId).digest()
        this.compactKey = `mcp:s:${digest.subarray(0, 16).toString('base64url')}:c`
    }

    async resolve(liveContext: MCPClientContext): Promise<SessionContext> {
        const cachedContext = await this.readCompact()
        const resolvedContext = mergeContexts(cachedContext ?? {}, liveContext)

        await this.refreshCompact(resolvedContext, cachedContext)

        sessionCacheOperationsTotal.inc({ schema: 'compact', operation: 'read' })
        return resolvedContext
    }

    private async readCompact(): Promise<SessionContext | null> {
        try {
            const raw = await this.redis.get(this.compactKey)
            return raw === null ? null : (JSON.parse(raw) as SessionContext)
        } catch (err) {
            // Session context is enrichment, not authorization — a Valkey blip degrades
            // attribution to whatever this request carries rather than failing the call.
            console.warn('[McpSessionRedisStore] compact read failed:', err)
            sessionCacheOperationsTotal.inc({ schema: 'compact', operation: 'read_error' })
            return null
        }
    }

    private async refreshCompact(context: SessionContext, cached: SessionContext | null): Promise<void> {
        try {
            if (cached !== null && contextsEqual(context, cached)) {
                await this.redis.expire(this.compactKey, COMPACT_IDLE_TTL_SECONDS)
                sessionCacheOperationsTotal.inc({ schema: 'compact', operation: 'refresh' })
            } else {
                await this.redis.eval(
                    MERGE_COMPACT_CONTEXT_SCRIPT,
                    1,
                    this.compactKey,
                    cached === null ? '' : JSON.stringify(cached),
                    JSON.stringify(context),
                    String(COMPACT_IDLE_TTL_SECONDS)
                )
                sessionCacheOperationsTotal.inc({ schema: 'compact', operation: 'write' })
            }
        } catch (err) {
            // A lost merge means this session's context stops persisting for the rest of
            // its life, so the request still succeeds while attribution silently decays.
            console.warn('[McpSessionRedisStore] compact write failed:', err)
            sessionCacheOperationsTotal.inc({ schema: 'compact', operation: 'write_error' })
        }
    }
}

function mergeContexts(stored: Partial<SessionContext>, live: MCPClientContext): SessionContext {
    return Object.fromEntries(SESSION_CONTEXT_KEYS.map((key) => [key, stored[key] ?? live[key]])) as SessionContext
}

function contextsEqual(left: Partial<SessionContext>, right: SessionContext): boolean {
    return SESSION_CONTEXT_KEYS.every((key) => left[key] === right[key])
}
