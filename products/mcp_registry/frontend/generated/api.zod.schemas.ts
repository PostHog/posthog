/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const MCPRegistryServerListApi = zod.object({
    id: zod.uuid().describe('Registry server id.'),
    registry_name: zod
        .string()
        .describe('Reverse-DNS name in the official MCP registry; empty for measured-only servers.'),
    display_name: zod.string().describe('Human-readable server name.'),
    description: zod.string().describe('Server description.'),
    canonical_url: zod.string().describe('Primary hosted remote URL; empty for package-only servers.'),
    liveness: zod.string().describe('Probed liveness state (alive_open, alive_auth, dead, ...).'),
    auth_method: zod.string().describe('Detected auth method (none, oauth, api_key, unknown).'),
    listed_in_registry: zod.boolean().describe('Whether the server appears in the official MCP registry.'),
    is_measured: zod.boolean().describe('Whether real usage signal exists via MCP Analytics.'),
    rank_score: zod
        .number()
        .describe('Static score under the requested ranking version; null when the version has no completed run.'),
})

export type MCPRegistryServerListApi = zod.input<typeof MCPRegistryServerListApi>
export type MCPRegistryServerListApiOutput = zod.output<typeof MCPRegistryServerListApi>

export const PaginatedMCPRegistryServerListListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid().describe('Registry server id.'),
            registry_name: zod
                .string()
                .describe('Reverse-DNS name in the official MCP registry; empty for measured-only servers.'),
            display_name: zod.string().describe('Human-readable server name.'),
            description: zod.string().describe('Server description.'),
            canonical_url: zod.string().describe('Primary hosted remote URL; empty for package-only servers.'),
            liveness: zod.string().describe('Probed liveness state (alive_open, alive_auth, dead, ...).'),
            auth_method: zod.string().describe('Detected auth method (none, oauth, api_key, unknown).'),
            listed_in_registry: zod.boolean().describe('Whether the server appears in the official MCP registry.'),
            is_measured: zod.boolean().describe('Whether real usage signal exists via MCP Analytics.'),
            rank_score: zod
                .number()
                .describe(
                    'Static score under the requested ranking version; null when the version has no completed run.'
                ),
        })
    ),
})

export type PaginatedMCPRegistryServerListListApi = zod.input<typeof PaginatedMCPRegistryServerListListApi>
export type PaginatedMCPRegistryServerListListApiOutput = zod.output<typeof PaginatedMCPRegistryServerListListApi>

export const MCPRegistryToolSourceEnumApi = zod
    .enum(['tools_list', 'analytics'])
    .describe('\* `tools_list` - tools_list\n\* `analytics` - analytics')

export type MCPRegistryToolSourceEnumApi = zod.input<typeof MCPRegistryToolSourceEnumApi>
export type MCPRegistryToolSourceEnumApiOutput = zod.output<typeof MCPRegistryToolSourceEnumApi>

export const MCPRegistryToolApi = zod.object({
    name: zod.string().describe('Tool name as advertised by the server (exec-resolved for measured servers).'),
    description: zod.string().describe('Tool description, from tools\/list or from observed calls.'),
    input_schema: zod
        .record(zod.string(), zod.unknown())
        .describe("JSON Schema for the tool's input. Only populated for probed (tools_list) tools."),
    source: zod
        .enum(['tools_list', 'analytics'])
        .describe('\* `tools_list` - tools_list\n\* `analytics` - analytics')
        .describe(
            'Where we learned about this tool: a probed tools\/list (authoritative schema) or MCP Analytics usage (proof of real calls, no schema).\n\n\* `tools_list` - tools_list\n\* `analytics` - analytics'
        ),
    last_seen_at: zod.iso.datetime({ offset: true }).describe('Last time this tool was observed by either source.'),
})

export type MCPRegistryToolApi = zod.input<typeof MCPRegistryToolApi>
export type MCPRegistryToolApiOutput = zod.output<typeof MCPRegistryToolApi>

export const MCPMeasuredStatsApi = zod.object({
    window_days: zod.number().describe('Aggregation window in days.'),
    calls: zod.number().describe('Tool calls observed in the window.'),
    sessions: zod.number().describe('Distinct MCP sessions observed in the window.'),
    errors: zod.number().describe('Errored tool calls in the window.'),
    error_rate_pct: zod.number().describe('Errors as a percentage of calls.'),
    intent_coverage_pct: zod.number().describe('Percentage of calls carrying an agent-written intent ($mcp_intent).'),
    distinct_tools: zod.number().describe('Distinct effective tools called in the window.'),
    harness_count: zod.number().describe('Distinct MCP client names observed in the window.'),
    tool_stats: zod
        .array(zod.looseObject({}))
        .describe('Per-tool usage, ordered by call volume: [{name, calls, errors, error_rate_pct}].'),
    link_method: zod
        .string()
        .describe(
            'How this measured source was attached to its registry entry (override | url | exact_name | standalone).'
        ),
    link_candidates: zod
        .array(zod.looseObject({}))
        .describe('Registry names that also matched when linking was ambiguous (kept for review).'),
    computed_at: zod.iso.datetime({ offset: true }).describe('When this aggregate was computed.'),
})

export type MCPMeasuredStatsApi = zod.input<typeof MCPMeasuredStatsApi>
export type MCPMeasuredStatsApiOutput = zod.output<typeof MCPMeasuredStatsApi>

export const MCPRankingScoreInfoApi = zod
    .object({
        version: zod.string().describe('Ranking version key (see the versions endpoint).'),
        score: zod.number().describe('Static score in [0, 1]; higher ranks first.'),
        components: zod
            .record(zod.string(), zod.unknown())
            .describe('Score inputs (liveness, trust, measured signals) for explainability.'),
        computed_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When the run producing this score completed.'),
    })
    .describe("One ranking version's latest score for a server.")

export type MCPRankingScoreInfoApi = zod.input<typeof MCPRankingScoreInfoApi>
export type MCPRankingScoreInfoApiOutput = zod.output<typeof MCPRankingScoreInfoApi>

export const MCPRegistryServerDetailApi = zod.object({
    id: zod.uuid().describe('Registry server id.'),
    registry_name: zod
        .string()
        .describe('Reverse-DNS name in the official MCP registry; empty for measured-only servers.'),
    display_name: zod.string().describe('Human-readable server name.'),
    description: zod.string().describe('Server description.'),
    canonical_url: zod.string().describe('Primary hosted remote URL; empty for package-only servers.'),
    liveness: zod.string().describe('Probed liveness state (alive_open, alive_auth, dead, ...).'),
    auth_method: zod.string().describe('Detected auth method (none, oauth, api_key, unknown).'),
    listed_in_registry: zod.boolean().describe('Whether the server appears in the official MCP registry.'),
    is_measured: zod.boolean().describe('Whether real usage signal exists via MCP Analytics.'),
    rank_score: zod
        .number()
        .describe('Static score under the requested ranking version; null when the version has no completed run.'),
    remotes: zod.array(zod.looseObject({})).describe('All hosted remotes: [{type, url}].'),
    packages: zod.array(zod.looseObject({})).describe('Published packages: [{registry_type, identifier}].'),
    repository_url: zod.string().describe('Source repository URL, when published.'),
    website_url: zod.string().describe('Vendor website URL, when published.'),
    last_probed_at: zod.iso.datetime({ offset: true }).nullable().describe('When the shallow probe last ran.'),
    tools: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .describe('Tool name as advertised by the server (exec-resolved for measured servers).'),
                description: zod.string().describe('Tool description, from tools\/list or from observed calls.'),
                input_schema: zod
                    .record(zod.string(), zod.unknown())
                    .describe("JSON Schema for the tool's input. Only populated for probed (tools_list) tools."),
                source: zod
                    .enum(['tools_list', 'analytics'])
                    .describe('\* `tools_list` - tools_list\n\* `analytics` - analytics')
                    .describe(
                        'Where we learned about this tool: a probed tools\/list (authoritative schema) or MCP Analytics usage (proof of real calls, no schema).\n\n\* `tools_list` - tools_list\n\* `analytics` - analytics'
                    ),
                last_seen_at: zod.iso
                    .datetime({ offset: true })
                    .describe('Last time this tool was observed by either source.'),
            })
        )
        .describe('Known tools, fused from probes and analytics.'),
    measured_stats: zod
        .array(
            zod.object({
                window_days: zod.number().describe('Aggregation window in days.'),
                calls: zod.number().describe('Tool calls observed in the window.'),
                sessions: zod.number().describe('Distinct MCP sessions observed in the window.'),
                errors: zod.number().describe('Errored tool calls in the window.'),
                error_rate_pct: zod.number().describe('Errors as a percentage of calls.'),
                intent_coverage_pct: zod
                    .number()
                    .describe('Percentage of calls carrying an agent-written intent ($mcp_intent).'),
                distinct_tools: zod.number().describe('Distinct effective tools called in the window.'),
                harness_count: zod.number().describe('Distinct MCP client names observed in the window.'),
                tool_stats: zod
                    .array(zod.looseObject({}))
                    .describe('Per-tool usage, ordered by call volume: [{name, calls, errors, error_rate_pct}].'),
                link_method: zod
                    .string()
                    .describe(
                        'How this measured source was attached to its registry entry (override | url | exact_name | standalone).'
                    ),
                link_candidates: zod
                    .array(zod.looseObject({}))
                    .describe('Registry names that also matched when linking was ambiguous (kept for review).'),
                computed_at: zod.iso.datetime({ offset: true }).describe('When this aggregate was computed.'),
            })
        )
        .describe('Behavioral aggregates, one per measured MCP Analytics project.'),
    scores: zod
        .array(
            zod
                .object({
                    version: zod.string().describe('Ranking version key (see the versions endpoint).'),
                    score: zod.number().describe('Static score in [0, 1]; higher ranks first.'),
                    components: zod
                        .record(zod.string(), zod.unknown())
                        .describe('Score inputs (liveness, trust, measured signals) for explainability.'),
                    computed_at: zod.iso
                        .datetime({ offset: true })
                        .nullable()
                        .describe('When the run producing this score completed.'),
                })
                .describe("One ranking version's latest score for a server.")
        )
        .describe('Latest score under every ranking version with a completed run.'),
    connect: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Connection instructions: methods ordered most-automated first, steps typed by actor (agent executes; human steps are narrated to the user).'
        ),
})

export type MCPRegistryServerDetailApi = zod.input<typeof MCPRegistryServerDetailApi>
export type MCPRegistryServerDetailApiOutput = zod.output<typeof MCPRegistryServerDetailApi>

export const MCPRankingVersionApi = zod
    .object({
        version: zod.string().describe('Ranking version key, passed as ?version= to the list endpoint.'),
        description: zod.string().describe('What this version scores on.'),
        is_default: zod.boolean().describe('Whether this is the version used when ?version= is omitted.'),
        latest_run: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Latest completed run: {id, server_count, computed_at}; null when the version never ran.'),
    })
    .describe('A registered ranking version and its latest completed run.')

export type MCPRankingVersionApi = zod.input<typeof MCPRankingVersionApi>
export type MCPRankingVersionApiOutput = zod.output<typeof MCPRankingVersionApi>
