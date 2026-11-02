/**
 * Writes tests/fixtures/rate-limiter-reference.json: a fixed sequence of calls through the
 * TypeScript KeyedRateLimiterService, LogsRateLimiterService and the sampling stage against a real
 * Redis, with every decision and the final bucket state. `tests/rate_limiter_redis.rs` replays the
 * same calls through the Rust port and compares.
 *
 * Needs Redis at 127.0.0.1:6379. Run from the repository root:
 *
 *   cd nodejs && NODE_ENV=test npx tsx --tsconfig tsconfig.json ../rust/logs-ingestion/scripts/node-rate-limiter-reference.ts
 */
import { writeFileSync } from 'fs'
import { join } from 'path'

import { createRedisV2PoolFromConfig } from '../../../nodejs/src/common/redis/redis-v2'
import { KeyedRateLimiterService } from '../../../nodejs/src/common/services/keyed-rate-limiter.service'
import { type LogRecord } from '../../../nodejs/src/logs/log-record-avro'
import { runPipelineStages } from '../../../nodejs/src/logs/pipeline/log-processing-pipeline'
import { compileRuleSet } from '../../../nodejs/src/logs/sampling/compile-rules'
import { LogsSamplingService } from '../../../nodejs/src/logs/sampling/logs-sampling.service'
import { LogsRateLimiterService } from '../../../nodejs/src/logs/services/logs-rate-limiter.service'

if (process.env.NODE_ENV !== 'test') {
    throw new Error('Run with NODE_ENV=test so keys use the @posthog-test root')
}

// Every limiter name starts with this, so the run never touches another test's keys.
const PREFIX = 'logs-parity-rl'
// The sampling limiter name is fixed, so its keys are kept apart by a team id no test uses.
const SAMPLING_TEAM = 987654321
const KEY_PATTERNS = [`@posthog-test/${PREFIX}*`, `@posthog-test/logs-sampling-rate/tokens/${SAMPLING_TEAM}/*`]
const T0 = Date.UTC(2025, 0, 15, 12, 0, 0, 0)

let nowMs = T0
Date.now = () => nowMs

const keyedLimiters = {
    v3: { name: `${PREFIX}-keyed-v3`, scriptVersion: 'v3' as const, ttlSeconds: 600 },
    v2: { name: `${PREFIX}-keyed-v2`, scriptVersion: 'v2' as const, ttlSeconds: 600 },
    grouped: { name: `${PREFIX}-grouped`, scriptVersion: 'v3' as const, ttlSeconds: 600 },
}

const logsLimiterConfigs = {
    all: {
        name: `${PREFIX}-logs-all`,
        config: {
            LOGS_LIMITER_ENABLED_TEAMS: '*',
            LOGS_LIMITER_DISABLED_FOR_TEAMS: '3, x',
            LOGS_LIMITER_BUCKET_SIZE_KB: 10,
            LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: 2,
            LOGS_LIMITER_TTL_SECONDS: 600,
            LOGS_LIMITER_TEAM_BUCKET_SIZE_KB: '2:25, 4 : 3, bad:1',
            LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: '2:5',
        },
    },
    listed: {
        name: `${PREFIX}-logs-listed`,
        config: {
            LOGS_LIMITER_ENABLED_TEAMS: '1,2',
            LOGS_LIMITER_DISABLED_FOR_TEAMS: '',
            LOGS_LIMITER_BUCKET_SIZE_KB: 4,
            LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: 1,
            LOGS_LIMITER_TTL_SECONDS: 600,
            LOGS_LIMITER_TEAM_BUCKET_SIZE_KB: '',
            LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: '',
        },
    },
}

type Req = { id: string; cost: number; bucketSize?: number; refillRate?: number; ttlSeconds?: number; now?: number }
type Msg = { teamId: number; bytesUncompressed: number; createdAt: string | null }

const sec = (s: number): number => T0 / 1000 + s
const iso = (s: number): string => new Date(T0 + s * 1000).toISOString()

const keyedSteps: { limiter: keyof typeof keyedLimiters; method: 'many' | 'grouped'; nowMs: number; requests: Req[] }[] =
    [
        // First call fills the bucket, an impossible cost does not burn credit.
        {
            limiter: 'v3',
            method: 'many',
            nowMs: T0,
            requests: [
                { id: 'a', cost: 3, bucketSize: 10, refillRate: 1, now: sec(0) },
                { id: 'b', cost: 15, bucketSize: 10, refillRate: 1, now: sec(0) },
                { id: 'c', cost: 2.5, bucketSize: 7.5, refillRate: 0.5, now: sec(0) },
            ],
        },
        {
            limiter: 'v3',
            method: 'many',
            nowMs: T0,
            requests: [
                { id: 'a', cost: 8, bucketSize: 10, refillRate: 1, now: sec(1) },
                { id: 'b', cost: 10, bucketSize: 10, refillRate: 1, now: sec(1) },
                { id: 'c', cost: 1, bucketSize: 7.5, refillRate: 0.5, now: sec(3) },
            ],
        },
        // Time goes backwards, then a long gap gives uncapped accrued credit.
        {
            limiter: 'v3',
            method: 'many',
            nowMs: T0,
            requests: [
                { id: 'a', cost: 1, bucketSize: 10, refillRate: 1, now: sec(-5) },
                { id: 'a', cost: 1, bucketSize: 10, refillRate: 1, now: sec(100) },
                { id: 'c', cost: 0.25, bucketSize: 7.5, refillRate: 0.5, now: sec(4) },
            ],
        },
        // `now` from the clock: Math.round of fractional seconds.
        {
            limiter: 'v3',
            method: 'many',
            nowMs: T0 + 200_500,
            requests: [
                { id: 'a', cost: 50, bucketSize: 10, refillRate: 1 },
                { id: 'd', cost: 1e-7, bucketSize: 1e21, refillRate: 3 },
            ],
        },
        {
            limiter: 'v2',
            method: 'many',
            nowMs: T0,
            requests: [
                { id: 'a', cost: 3, bucketSize: 10, refillRate: 1, now: sec(0) },
                { id: 'b', cost: 15, bucketSize: 10, refillRate: 1, now: sec(0) },
                { id: 'c', cost: 2.5, bucketSize: 7.5, refillRate: 0.5, now: sec(0) },
            ],
        },
        {
            limiter: 'v2',
            method: 'many',
            nowMs: T0,
            requests: [
                { id: 'a', cost: 8, bucketSize: 10, refillRate: 1, now: sec(1) },
                { id: 'b', cost: 10, bucketSize: 10, refillRate: 1, now: sec(1) },
                { id: 'c', cost: 6, bucketSize: 7.5, refillRate: 0.5, now: sec(3) },
                { id: 'a', cost: 1, bucketSize: 10, refillRate: 1, now: sec(-5) },
            ],
        },
        {
            limiter: 'grouped',
            method: 'grouped',
            nowMs: T0,
            requests: [
                { id: 'x', cost: 2, bucketSize: 5, refillRate: 1, now: sec(0) },
                { id: 'y', cost: 4, bucketSize: 3, refillRate: 1, now: sec(0) },
                { id: 'x', cost: 3, bucketSize: 99, refillRate: 50, now: sec(50) },
                { id: 'x', cost: 1, now: sec(0) },
                { id: 'y', cost: 1 },
            ],
        },
        {
            limiter: 'grouped',
            method: 'grouped',
            nowMs: T0 + 2000,
            requests: [
                { id: 'x', cost: 1, bucketSize: 5, refillRate: 1 },
                { id: 'x', cost: 1, bucketSize: 5, refillRate: 1 },
                { id: 'y', cost: 0.5, bucketSize: 3, refillRate: 1 },
                { id: 'x', cost: 1, bucketSize: 5, refillRate: 1 },
            ],
        },
    ]

const logsSteps: { limiter: keyof typeof logsLimiterConfigs; nowMs: number; messages: Msg[] }[] = [
    {
        limiter: 'all',
        nowMs: T0,
        messages: [
            { teamId: 1, bytesUncompressed: 4000, createdAt: iso(0) },
            { teamId: 1, bytesUncompressed: 4001, createdAt: iso(0.4) },
            { teamId: 1, bytesUncompressed: 3000, createdAt: iso(-3) },
            { teamId: 2, bytesUncompressed: 20_000, createdAt: iso(0) },
            { teamId: 2, bytesUncompressed: 6000, createdAt: 'Wed, 15 Jan 2025 12:00:01 GMT' },
            { teamId: 3, bytesUncompressed: 99_000, createdAt: null },
            { teamId: 3, bytesUncompressed: 99_000, createdAt: 'not a date' },
            { teamId: 4, bytesUncompressed: 1, createdAt: iso(0.5) },
            { teamId: 4, bytesUncompressed: 2500, createdAt: iso(0.5) },
            { teamId: 1, bytesUncompressed: 1, createdAt: iso(0) },
        ],
    },
    {
        limiter: 'all',
        nowMs: T0,
        messages: [
            { teamId: 1, bytesUncompressed: 3500, createdAt: iso(2) },
            { teamId: 1, bytesUncompressed: 1500, createdAt: iso(1) },
            { teamId: 2, bytesUncompressed: 10_000, createdAt: iso(1) },
            { teamId: 4, bytesUncompressed: 999, createdAt: iso(9) },
        ],
    },
    {
        limiter: 'listed',
        nowMs: T0,
        messages: [
            { teamId: 1, bytesUncompressed: 3000, createdAt: iso(0) },
            { teamId: 1, bytesUncompressed: 1000, createdAt: iso(0) },
            { teamId: 2, bytesUncompressed: 5000, createdAt: iso(0) },
            { teamId: 5, bytesUncompressed: 1e9, createdAt: '' },
            { teamId: 1, bytesUncompressed: 1, createdAt: iso(0) },
        ],
    },
]

const rec = (uuid: string, extra: Partial<LogRecord>): LogRecord =>
    ({
        uuid,
        trace_id: Buffer.from('0102030405060708090a0b0c0d0e0f10', 'hex'),
        span_id: null,
        trace_flags: null,
        timestamp: T0 * 1000,
        observed_timestamp: T0 * 1000,
        body: 'request handled',
        severity_text: 'INFO',
        severity_number: 9,
        service_name: 'api',
        resource_attributes: { 'service.name': '"api"' },
        instrumentation_scope: null,
        event_name: null,
        attributes: { 'url.path': '"/api/items"' },
        bytes_uncompressed: 200,
        ...extra,
    }) as LogRecord

const samplingRules = [
    {
        id: 'drop-health',
        rule_type: 'path_drop',
        scope_service: null,
        scope_path_pattern: null,
        scope_attribute_filters: [],
        config: { patterns: ['healthz'], match_attribute_key: 'url.path' },
    },
    {
        id: 'rl-records',
        rule_type: 'rate_limit',
        scope_service: 'api',
        scope_path_pattern: null,
        scope_attribute_filters: [],
        config: { logs_per_second: 2, burst_logs: 3 },
    },
    {
        id: 'rl-bytes',
        rule_type: 'rate_limit',
        scope_service: null,
        scope_path_pattern: null,
        scope_attribute_filters: [],
        config: { kb_per_second: 1, burst_kb: 1 },
    },
]

const samplingBatches: { nowMs: number; teamId: number; headerBytes: number; records: LogRecord[] }[] = [
    {
        nowMs: T0,
        teamId: SAMPLING_TEAM,
        headerBytes: 0,
        records: [
            rec('r0', {}),
            rec('r1', { attributes: { 'url.path': '"/healthz"' } }),
            rec('r2', {}),
            rec('r3', { service_name: 'worker', bytes_uncompressed: 400 }),
            rec('r4', {}),
            rec('r5', { service_name: 'worker', bytes_uncompressed: 500 }),
            rec('r6', {}),
            rec('r7', { service_name: 'worker', bytes_uncompressed: null }),
            rec('r8', { service_name: 'worker', bytes_uncompressed: 300 }),
        ],
    },
    {
        nowMs: T0 + 1400,
        teamId: SAMPLING_TEAM,
        headerBytes: 2500,
        records: [
            rec('s0', {}),
            rec('s1', { service_name: 'worker', body: 'x'.repeat(300) }),
            rec('s2', { service_name: 'worker', body: 'y'.repeat(100), resource_attributes: null }),
            rec('s3', {}),
            rec('s4', { service_name: 'worker', instrumentation_scope: 'scope@1' }),
        ],
    },
]

const recordJson = (r: LogRecord): unknown =>
    Object.fromEntries(
        Object.entries(r).map(([k, v]) => [k, Buffer.isBuffer(v) ? { $bytes: v.toString('hex') } : v])
    )

async function main(): Promise<void> {
    const redis = createRedisV2PoolFromConfig({
        connection: { url: 'redis://127.0.0.1:6379' },
        poolMinSize: 1,
        poolMaxSize: 1,
    })
    const scan = async (): Promise<string[]> => {
        const keys: string[] = []
        for (const pattern of KEY_PATTERNS) {
            keys.push(...((await redis.useClient({ name: 'scan' }, (c) => c.keys(pattern))) ?? []))
        }
        return keys
    }
    const existing = await scan()
    if (existing.length > 0) {
        await redis.useClient({ name: 'del' }, (c) => c.del(...existing))
    }

    const keyed = Object.fromEntries(
        Object.entries(keyedLimiters).map(([k, cfg]) => [k, new KeyedRateLimiterService(cfg, redis)])
    ) as Record<keyof typeof keyedLimiters, KeyedRateLimiterService>
    const steps: unknown[] = []
    for (const step of keyedSteps) {
        nowMs = step.nowMs
        const limiter = keyed[step.limiter]
        const requests = step.requests.map((r) => ({ ...r }))
        const output =
            step.method === 'many' ? await limiter.rateLimitMany(requests) : await limiter.rateLimitGrouped(requests)
        steps.push({ kind: 'keyed', ...step, output })
    }

    const logsLimiters = Object.fromEntries(
        Object.entries(logsLimiterConfigs).map(([k, { name, config }]) => [
            k,
            new LogsRateLimiterService(config, redis, name),
        ])
    ) as Record<keyof typeof logsLimiterConfigs, LogsRateLimiterService>
    for (const step of logsSteps) {
        nowMs = step.nowMs
        const messages = step.messages.map((m, index) => ({
            index,
            teamId: m.teamId,
            bytesUncompressed: m.bytesUncompressed,
            message: { headers: m.createdAt === null ? [] : [{ created_at: Buffer.from(m.createdAt) }] },
        }))
        const { allowed, dropped } = await logsLimiters[step.limiter].filterMessages(messages as any)
        steps.push({
            kind: 'logs',
            ...step,
            output: { allowed: allowed.map((m: any) => m.index), dropped: dropped.map((m: any) => m.index) },
        })
    }

    const sampling = new LogsSamplingService(redis, 600)
    const ruleSet = compileRuleSet(samplingRules)
    for (const batch of samplingBatches) {
        nowMs = batch.nowMs
        const input = batch.records.map(recordJson)
        const stage = sampling.makeSamplingStage(ruleSet, batch.teamId, batch.headerBytes)
        const { kept, stats } = await runPipelineStages(batch.records, [stage])
        steps.push({
            kind: 'sampling',
            nowMs: batch.nowMs,
            teamId: batch.teamId,
            headerBytes: batch.headerBytes,
            records: input,
            output: {
                kept: kept.map((r) => r.uuid),
                recordsDropped: stats.recordsDropped,
                recordsDroppedByRuleId: [...stats.recordsDroppedByRuleId],
                bytesDropped: stats.bytesDropped,
                bytesDroppedByRuleId: [...stats.bytesDroppedByRuleId],
                contentBytesDropped: stats.contentBytesDropped,
                contentBytesTotal: stats.contentBytesTotal,
                droppedBy: stats.droppedBy ?? null,
            },
        })
    }

    const finalState: Record<string, Record<string, string>> = {}
    for (const key of (await scan()).sort()) {
        finalState[key] = (await redis.useClient({ name: 'state' }, (c) => c.hgetall(key))) ?? {}
    }
    const shas = await redis.useClient({ name: 'shas' }, async (c) => {
        const set = (c as any).scriptsSet
        return { v2: set.checkRateLimitV2.sha, v3: set.checkRateLimitV3.sha }
    })

    const out = {
        keyPatterns: KEY_PATTERNS,
        keyedLimiters,
        logsLimiters: logsLimiterConfigs,
        samplingRules,
        shas,
        steps,
        finalState,
    }
    writeFileSync(join(__dirname, '../tests/fixtures/rate-limiter-reference.json'), JSON.stringify(out, null, 1) + '\n')
    process.exit(0)
}

void main()
