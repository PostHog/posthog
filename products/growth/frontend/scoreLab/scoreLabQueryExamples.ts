// The query runs as HogQL against this PostHog project, so any real synced table is fair game
// (events, persons, groups, data warehouse). These starters stick to postgres.growth_organizationenrichmentfetch
// since it's the one table known to hold useful, currently-synced org data - swap in events/persons/groups
// once there's a similarly concrete example worth shipping.
export interface ScoreLabQueryExample {
    label: string
    query: string
}

export const SCORE_LAB_QUERY_EXAMPLES: ScoreLabQueryExample[] = [
    {
        label: 'Recent enrichment fetches',
        query: `SELECT organization_id, payload, provider, fetched_at
FROM postgres.growth_organizationenrichmentfetch
WHERE NOT is_recheck
ORDER BY fetched_at DESC
LIMIT 100`,
    },
    {
        label: 'One provider only',
        query: `SELECT organization_id, payload, fetched_at
FROM postgres.growth_organizationenrichmentfetch
WHERE provider = 'harmonic' AND NOT is_recheck
ORDER BY fetched_at DESC
LIMIT 100`,
    },
]

export interface ScoreLabReferenceColumn {
    name: string
    type: string
}

export interface ScoreLabReferenceTable {
    table: string
    description: string
    columns: ScoreLabReferenceColumn[]
}

export const SCORE_LAB_REFERENCE_TABLES: ScoreLabReferenceTable[] = [
    {
        table: 'postgres.growth_organizationenrichmentfetch',
        description: 'One row per archived enrichment call for an organization.',
        columns: [
            { name: 'id', type: 'String' },
            { name: 'payload', type: 'JSON' },
            { name: 'provider', type: 'String' },
            { name: 'fetched_at', type: 'DateTime' },
            { name: 'is_recheck', type: 'Boolean' },
            { name: 'organization_id', type: 'String' },
        ],
    },
]
