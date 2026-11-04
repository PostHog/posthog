import { z } from 'zod'

import { MCP_SCOPE_PRESET, type McpScopePreset } from '@/lib/scope-preset'

import type { GuidanceCall } from './engine'
import type { GuidanceProductState } from './product-state'

const scopePresets = Object.values(MCP_SCOPE_PRESET) as [McpScopePreset, ...McpScopePreset[]]

type GuidanceCondition = (input: {
    call: GuidanceCall
    productState: GuidanceProductState
}) => boolean | Promise<boolean>
type GuidanceText = (call: GuidanceCall) => string

const guidanceRuleSchema = z.object({
    id: z.string().regex(/^[a-z0-9-]+$/),
    /** The feature flag that turns the rule on for a caller. Every rule ships off. */
    flag: z.string().min(1),
    trigger: z.object({
        /** Effective tool name (the inner tool for exec calls). A trailing `*` matches a prefix. */
        tool: z.string().min(1).optional(),
        /** A non-call exec verb such as `search`. The effective tool name is `exec` for those. */
        execVerb: z.string().min(1).optional(),
        /** Dot path into the call arguments whose string value `argPattern` must match. */
        argPath: z.string().min(1).optional(),
        argPattern: z.instanceof(RegExp).optional(),
        /** A longer `argPath` value never matches, so `argPattern` only runs on bounded input. */
        argMaxLength: z.number().int().min(1).optional(),
        /** Call arguments that rule the call out when they are set, such as a target outside the project. */
        excludeArgs: z.array(z.string().min(1)).optional(),
        resultEmpty: z.boolean().optional(),
        outcome: z.enum(['any', 'success', 'error']),
        presets: z.array(z.enum(scopePresets)).min(1),
    }),
    /** The notice is shown once the session's matching-call count reaches this. */
    threshold: z.number().int().min(1),
    maxPerSession: z.number().int().min(1),
    /** Once the session has called any of these (same `*` prefix syntax), the rule stays silent. */
    suppressIfCalled: z.array(z.string().min(1)),
    /** Every tool the notice names, so it never points at one the caller's roster lacks. */
    requiresTool: z.array(z.string().min(1)).min(1),
    /** The notice sends the agent to an AI feature, so it is withheld (and stamped) without org consent. */
    requiresAiConsent: z.boolean().optional(),
    /** Runs for every outcome, so `shown` and `flag_off` callers stay comparable. A rejected call is not counted. */
    condition: z.custom<GuidanceCondition>((value) => typeof value === 'function').optional(),
    text: z.union([z.string().min(1).max(2000), z.custom<GuidanceText>((value) => typeof value === 'function')]),
})

export type GuidanceRule = z.infer<typeof guidanceRuleSchema>

export const MCP_GUIDANCE_REPLAY_VISION_FLAG = 'mcp-guidance-replay-vision'
export const MCP_GUIDANCE_SQL_SCHEMA_FLAG = 'mcp-guidance-sql-schema'
export const MCP_GUIDANCE_SQL_TYPED_RUNNER_FLAG = 'mcp-guidance-sql-typed-runner'

const TYPED_RUNNER_TOOLS = [
    'query-trends',
    'query-funnel',
    'query-retention',
    'query-stickiness',
    'query-paths',
    'query-lifecycle',
]

// A query with any of these constructs needs SQL, so the typed-runner hint stays silent. A first or
// last timestamp grouped by event is an event inventory, which `read-data-schema` answers. The scans
// after `max(timestamp` and `GROUP BY` are bounded, because an unbounded scan takes quadratic time.
const SQL_ONLY_CONSTRUCTS = [
    String.raw`\b(JOIN|WITH|OVER|UNION|HAVING)\b`,
    String.raw`\bFROM\s+events\b(?:\s+(?:AS\s+)?\w+)?\s*,`,
    String.raw`\bsystem\.`,
    String.raw`\(\s*SELECT\b`,
    String.raw`\barray\w*\s*\(`,
    String.raw`\b(groupArray|groupUniqArray|argMax|argMin|dateDiff|date_diff)\w*\s*\(`,
    String.raw`\b(max|min)(If)?\s*\(\s*(\w+\.)?timestamp\b(?![\s\S]{0,1000}\bGROUP\s+BY\s+event\b)`,
    String.raw`\bGROUP\s+BY\b(?:(?!\b(ORDER|LIMIT)\b)[\s\S]){0,300}?\b(person_id|distinct_id|session_id)\b`,
    String.raw`(\bSELECT\b|,)\s*(DISTINCT\s+)?(\w+\.)*\$?(person_id|distinct_id|session_id)\b\s*(AS\s+\w+\s*)?(,|\bFROM\b)`,
]
const SIMPLE_EVENTS_AGGREGATE = new RegExp(
    String.raw`^(?![\s\S]*(${SQL_ONLY_CONSTRUCTS.join('|')}))(?=[\s\S]*\bFROM\s+events\b)(?=[\s\S]*\b(count|uniq)\w*\s*\()`,
    'i'
)

const RULES: GuidanceRule[] = [
    {
        id: 'replay-sql-to-vision',
        flag: MCP_GUIDANCE_REPLAY_VISION_FLAG,
        trigger: {
            tool: 'execute-sql',
            argPath: 'query',
            argPattern:
                /\b(raw_)?session_replay_(events|features)\b|\bconsole_logs_log_entries\b|\bsystem\.session_recordings\b/i,
            outcome: 'any',
            presets: ['user'],
        },
        threshold: 2,
        maxPerSession: 1,
        suppressIfCalled: ['vision-*', 'inline-scan'],
        requiresTool: [
            'vision-scanners-inline-scan',
            'vision-requests-create',
            'vision-requests-get',
            'vision-observations-search',
        ],
        requiresAiConsent: true,
        text: [
            'SQL over session replay tables returns recording metadata (duration, event counts, URLs), not what happened in the session.',
            'To answer a question about what users did or saw, Replay Vision can watch the recordings for you:',
            'call `vision-scanners-inline-scan` with `session_ids` and either `built_in: "summarize_recording"` for a',
            'general summary or a `prompt` for a specific question, for sessions you already have,',
            'or `vision-requests-create` for up to 200 sessions and poll `vision-requests-get` for the results.',
            '`vision-observations-search` finds observations from earlier scans by meaning.',
            'Keep using SQL when the user only needs recording metadata.',
        ].join(' '),
    },
    {
        id: 'sql-failures-to-schema',
        flag: MCP_GUIDANCE_SQL_SCHEMA_FLAG,
        trigger: {
            tool: 'execute-sql',
            outcome: 'error',
            presets: ['user', 'scout'],
        },
        threshold: 3,
        maxPerSession: 1,
        suppressIfCalled: ['read-data-schema'],
        requiresTool: ['read-data-schema'],
        text: [
            'Three SQL queries in this session have failed.',
            'Before another attempt, check the schema: query `system.information_schema.tables` and',
            '`system.information_schema.columns` for table and column names, or call `read-data-schema` for',
            'event and property names. Then rewrite the query against that schema.',
        ].join(' '),
    },
    {
        id: 'sql-aggregate-to-typed-runner',
        flag: MCP_GUIDANCE_SQL_TYPED_RUNNER_FLAG,
        trigger: {
            tool: 'execute-sql',
            argPath: 'query',
            argPattern: SIMPLE_EVENTS_AGGREGATE,
            argMaxLength: 4000,
            // A direct warehouse connection has its own `events` table, which typed runners cannot query.
            excludeArgs: ['connectionId'],
            outcome: 'success',
            presets: ['user'],
        },
        threshold: 1,
        maxPerSession: 1,
        suppressIfCalled: TYPED_RUNNER_TOOLS,
        requiresTool: ['query-trends', 'query-funnel', 'read-data-schema'],
        text: [
            'This SQL is a simple aggregate over events.',
            'Before you report these numbers, run the same calculation with `query-trends`,',
            'or with `query-funnel` for conversion between steps, and report that result.',
            "The typed runner applies the project's default test account filter, which raw SQL does not apply,",
            'so the numbers can differ.',
            'Keep this SQL only when the user asked for SQL or the runners cannot express the calculation.',
            'To only check that an event or property exists, use `read-data-schema`.',
        ].join(' '),
    },
]

export const GUIDANCE_RULES: readonly GuidanceRule[] = z.array(guidanceRuleSchema).parse(RULES)

export const GUIDANCE_RULE_FLAGS: readonly string[] = [...new Set(GUIDANCE_RULES.map((rule) => rule.flag))]
