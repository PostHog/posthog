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
        .nullable()
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
                .nullable()
                .describe(
                    'Static score under the requested ranking version; null when the version has no completed run.'
                ),
        })
    ),
})

export type PaginatedMCPRegistryServerListListApi = zod.input<typeof PaginatedMCPRegistryServerListListApi>
export type PaginatedMCPRegistryServerListListApiOutput = zod.output<typeof PaginatedMCPRegistryServerListListApi>

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
        .nullable()
        .describe('Static score under the requested ranking version; null when the version has no completed run.'),
    remotes: zod
        .array(
            zod.object({
                type: zod.string().optional(),
                url: zod.string().optional(),
            })
        )
        .describe('All hosted remotes: [{type, url}].'),
    packages: zod
        .array(
            zod.object({
                registry_type: zod.string().optional(),
                identifier: zod.string().optional(),
            })
        )
        .describe('Published packages: [{registry_type, identifier}].'),
    repository_url: zod.string().describe('Source repository URL, when published.'),
    website_url: zod.string().describe('Vendor website URL, when published.'),
    last_probed_at: zod.iso.datetime({ offset: true }).nullable().describe('When the shallow probe last ran.'),
    tools: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            "Known tools, fused from probes and analytics. A tool known only from another project's traffic is limited to callers who may see that project's measurements."
        ),
    measured_stats: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            "Behavioral aggregates, one per measured MCP Analytics project. Limited to this project's own measurements unless the server is marked measured_public."
        ),
    scores: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('Latest score under every ranking version with a completed run.'),
    connect: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Connection instructions: methods ordered most-automated first, steps typed by actor (agent executes; human steps are narrated to the user).'
        ),
})

export type MCPRegistryServerDetailApi = zod.input<typeof MCPRegistryServerDetailApi>
export type MCPRegistryServerDetailApiOutput = zod.output<typeof MCPRegistryServerDetailApi>

export const MCPDiscoverCandidateApi = zod
    .object({
        rank: zod.number().describe('1-based position under the ranking version used.'),
        id: zod.uuid().describe('Registry server id, for the detail endpoint.'),
        registry_name: zod.string().describe('Official registry name, empty for measured-only servers.'),
        title: zod.string().describe('Human-readable server name.'),
        description: zod.string().describe('What the server does.'),
        score: zod.number().describe('Rank score in [0, 1] under the ranking version used.'),
        why: zod
            .record(zod.string(), zod.unknown())
            .describe(
                'Score breakdown so an agent can explain its choice: fit, liveness, trust, and whether real usage signal contributed.'
            ),
        liveness: zod.string().describe('Probed liveness state (alive_open, alive_auth, dead, ...).'),
        auth_method: zod.string().describe('Detected auth method (none, oauth, api_key, unknown).'),
        measured: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe(
                'Real MCP Analytics aggregates when the server is measured, otherwise null: calls, sessions, error_rate_pct, intent_coverage_pct, harness_count.'
            ),
        matched_tools: zod
            .array(
                zod.object({
                    name: zod.string().optional(),
                    description: zod.string().optional(),
                    source: zod.string().optional(),
                })
            )
            .describe(
                'Tools that matched the intent: [{name, description, source}]. Empty when only the server description matched.'
            ),
        connect: zod
            .record(zod.string(), zod.unknown())
            .describe(
                'Connection instructions, most-automated method first, steps typed by actor so the agent runs its own steps and narrates the human ones.'
            ),
    })
    .describe('One ranked candidate in a discover response, with everything an agent needs to act.')

export type MCPDiscoverCandidateApi = zod.input<typeof MCPDiscoverCandidateApi>
export type MCPDiscoverCandidateApiOutput = zod.output<typeof MCPDiscoverCandidateApi>

export const MCPDiscoverResponseApi = zod
    .object({
        intent: zod.string().describe('The intent the candidates were ranked against, echoed back.'),
        ranking_version: zod.string().describe('Ranking version the candidates were ordered by.'),
        candidates: zod
            .array(
                zod
                    .object({
                        rank: zod.number().describe('1-based position under the ranking version used.'),
                        id: zod.uuid().describe('Registry server id, for the detail endpoint.'),
                        registry_name: zod
                            .string()
                            .describe('Official registry name, empty for measured-only servers.'),
                        title: zod.string().describe('Human-readable server name.'),
                        description: zod.string().describe('What the server does.'),
                        score: zod.number().describe('Rank score in [0, 1] under the ranking version used.'),
                        why: zod
                            .record(zod.string(), zod.unknown())
                            .describe(
                                'Score breakdown so an agent can explain its choice: fit, liveness, trust, and whether real usage signal contributed.'
                            ),
                        liveness: zod.string().describe('Probed liveness state (alive_open, alive_auth, dead, ...).'),
                        auth_method: zod.string().describe('Detected auth method (none, oauth, api_key, unknown).'),
                        measured: zod
                            .record(zod.string(), zod.unknown())
                            .nullable()
                            .describe(
                                'Real MCP Analytics aggregates when the server is measured, otherwise null: calls, sessions, error_rate_pct, intent_coverage_pct, harness_count.'
                            ),
                        matched_tools: zod
                            .array(
                                zod.object({
                                    name: zod.string().optional(),
                                    description: zod.string().optional(),
                                    source: zod.string().optional(),
                                })
                            )
                            .describe(
                                'Tools that matched the intent: [{name, description, source}]. Empty when only the server description matched.'
                            ),
                        connect: zod
                            .record(zod.string(), zod.unknown())
                            .describe(
                                'Connection instructions, most-automated method first, steps typed by actor so the agent runs its own steps and narrates the human ones.'
                            ),
                    })
                    .describe('One ranked candidate in a discover response, with everything an agent needs to act.')
            )
            .describe('Servers most likely to do the thing, best first.'),
    })
    .describe('Everything an agent gets back from one discover call.')

export type MCPDiscoverResponseApi = zod.input<typeof MCPDiscoverResponseApi>
export type MCPDiscoverResponseApiOutput = zod.output<typeof MCPDiscoverResponseApi>

export const MCPMeasuredProjectApi = zod
    .object({
        team_id: zod.number().describe('Project supplying the MCP Analytics signal.'),
        servers: zod.number().describe('Distinct servers this project has measured.'),
        calls: zod.number().describe('Tool calls this project contributes across those servers.'),
    })
    .describe("One project's contribution to the measured layer, for the staff fleet view.")

export type MCPMeasuredProjectApi = zod.input<typeof MCPMeasuredProjectApi>
export type MCPMeasuredProjectApiOutput = zod.output<typeof MCPMeasuredProjectApi>

export const MCPRankingRunApi = zod
    .object({
        id: zod.uuid().describe('Run id.'),
        server_count: zod.number().describe('Servers scored in the run.'),
        computed_at: zod.iso.datetime({ offset: true }).nullable().describe('When the run completed.'),
    })
    .describe('A completed ranking run.')

export type MCPRankingRunApi = zod.input<typeof MCPRankingRunApi>
export type MCPRankingRunApiOutput = zod.output<typeof MCPRankingRunApi>

export const MCPRankingVersionApi = zod
    .object({
        version: zod.string().describe('Ranking version key, passed as ?version= to the list endpoint.'),
        description: zod.string().describe('What this version scores on.'),
        is_default: zod.boolean().describe('Whether this is the version used when ?version= is omitted.'),
        latest_run: zod
            .union([
                zod
                    .object({
                        id: zod.uuid().describe('Run id.'),
                        server_count: zod.number().describe('Servers scored in the run.'),
                        computed_at: zod.iso.datetime({ offset: true }).nullable().describe('When the run completed.'),
                    })
                    .describe('A completed ranking run.'),
                zod.null(),
            ])
            .describe('Latest completed run; null when the version never ran.'),
    })
    .describe('A registered ranking version and its latest completed run.')

export type MCPRankingVersionApi = zod.input<typeof MCPRankingVersionApi>
export type MCPRankingVersionApiOutput = zod.output<typeof MCPRankingVersionApi>
