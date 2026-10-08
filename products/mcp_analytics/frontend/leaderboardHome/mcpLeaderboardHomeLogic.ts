import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import posthog from 'lib/posthog-typed'
import { normalizeBucket } from 'lib/utils/timeBuckets'

import { HogQLFilters, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { bucketExpr, mcpDashboardOverviewLogic } from '../mcpDashboardOverviewLogic'
import {
    type BucketedFacetRow,
    buildLabShares,
    buildLabUserShares,
    buildReliabilitySeries,
    buildShareSeries,
    type LabShare,
    type LabUsersRow,
    labSqlExpression,
    modelLab,
    type ReliabilityRow,
    type ReliabilitySeries,
    type ScoreboardMetric,
    type ShareSeries,
    type WindowFacetRow,
} from './leaderboardShares'

const MODEL_SERIES_LIMIT = 8
const PROTOCOL_SERIES_LIMIT = 5

// Key on the canonical event only, like the overview queries. `{filters}` carries the date range,
// the property filters and the internal users filter.
const TOOL_CALL_WHERE = `event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}`

const BUCKETED_ROW_LIMIT = 10000
const WINDOW_ROW_LIMIT = 1000

const labelOf = (valueSql: string): string => `coalesce(nullIf(trim(${valueSql}), ''), 'Unknown')`

const propertyLabel = (property: string): string => labelOf(`toString(properties.${property})`)

// The protocol version can be inferred as a DateTime property, so read the raw string like
// MCPProtocolVersionBreakdownQueryRunner (backend/hogql_queries/protocol_version_breakdown.py).
const PROTOCOL_VERSION_LABEL = labelOf("JSONExtractString(properties, '$mcp_protocol_version')")

// Mirrors EFFECTIVE_TOOL_SQL (backend/hogql_queries/base.py): a single-exec call counts as the inner tool.
const TOOL_LABEL = labelOf(`coalesce(
    nullIf(toString(properties.$mcp_exec_tool_call_name), ''),
    if(properties.$mcp_tool_name = 'exec' AND properties.$mcp_exec_verb = 'call',
       nullIf(nullIf(toString(properties.$mcp_exec_target_tool), ''), 'unrecognized'), NULL),
    toString(properties.$mcp_tool_name)
)`)

const bucketedFacetQuery = (label: string, interval: IntervalType): string => `
SELECT ${bucketExpr(interval)} AS bucket, ${label} AS label, count() AS calls
FROM events
WHERE ${TOOL_CALL_WHERE}
GROUP BY bucket, label
ORDER BY bucket
LIMIT ${BUCKETED_ROW_LIMIT}
`

const windowFacetQuery = (label: string, onlyErrors = false): string => `
SELECT
    ${label} AS label,
    count() AS calls,
    uniq(person_id) AS users,
    countIf(toBool(properties.$mcp_is_error)) AS errors
FROM events
WHERE ${TOOL_CALL_WHERE}
    ${onlyErrors ? 'AND toBool(properties.$mcp_is_error)' : ''}
GROUP BY label
ORDER BY calls DESC
LIMIT ${WINDOW_ROW_LIMIT}
`

const MODEL_LABEL = propertyLabel('$mcp_llm_model')

const labUsersQuery = `
SELECT ${labSqlExpression(MODEL_LABEL)} AS lab, uniq(person_id) AS users
FROM events
WHERE ${TOOL_CALL_WHERE}
GROUP BY lab
`

const namedModelUsersQuery = `
SELECT uniqIf(person_id, ${MODEL_LABEL} != 'Unknown') AS users
FROM events
WHERE ${TOOL_CALL_WHERE}
`

const reliabilityQuery = (interval: IntervalType): string => `
SELECT
    ${bucketExpr(interval)} AS bucket,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95
FROM events
WHERE ${TOOL_CALL_WHERE}
GROUP BY bucket
ORDER BY bucket
LIMIT ${BUCKETED_ROW_LIMIT}
`

export interface LeaderboardFacets {
    model: BucketedFacetRow[]
    protocolVersion: BucketedFacetRow[]
    toolCategory: WindowFacetRow[]
    tool: WindowFacetRow[]
    intentSource: WindowFacetRow[]
    errorType: WindowFacetRow[]
    authMethod: WindowFacetRow[]
    modelSource: WindowFacetRow[]
    labUsers: LabUsersRow[]
    namedModelUsers: number
    failedFacets: FacetKey[]
}

export type FacetKey = Exclude<keyof LeaderboardFacets, 'failedFacets'>

const EMPTY_FACETS: LeaderboardFacets = {
    model: [],
    protocolVersion: [],
    toolCategory: [],
    tool: [],
    intentSource: [],
    errorType: [],
    authMethod: [],
    modelSource: [],
    labUsers: [],
    namedModelUsers: 0,
    failedFacets: [],
}

type Row = unknown[]

async function runQuery(query: string, filters: HogQLFilters): Promise<Row[]> {
    const response = (await api.query({ kind: NodeKind.HogQLQuery, query, filters })) as HogQLQueryResponse
    return (response?.results as Row[]) ?? []
}

const toBucketedRows = (rows: Row[]): BucketedFacetRow[] =>
    rows.map((r) => ({ bucket: normalizeBucket(r[0]), label: String(r[1]), calls: Number(r[2]) }))

const toReliabilityRows = (rows: Row[]): ReliabilityRow[] =>
    rows.map((r) => ({
        bucket: normalizeBucket(r[0]),
        calls: Number(r[1]),
        errors: Number(r[2]),
        p50: Number(r[3]),
        p95: Number(r[4]),
    }))

const toWindowRows = (rows: Row[]): WindowFacetRow[] =>
    rows.map((r) => ({ label: String(r[0]), calls: Number(r[1]), users: Number(r[2]), errors: Number(r[3]) }))

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpLeaderboardHomeLogicValues {
    bucketKeys: string[] // mcpDashboardOverviewLogic
    interval: IntervalType // mcpDashboardOverviewLogic
    queryFilters: HogQLFilters // mcpDashboardOverviewLogic
    facets: LeaderboardFacets
    facetsLoading: boolean
    labSeries: ShareSeries[]
    labShares: LabShare[]
    leaderboardLoading: boolean
    modelSeries: ShareSeries[]
    protocolVersionSeries: ShareSeries[]
    reliabilityRows: ReliabilityRow[]
    reliabilityRowsLoading: boolean
    reliabilitySeries: ReliabilitySeries
    scoreboardMetric: ScoreboardMetric
    scoreboardShares: LabShare[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpLeaderboardHomeLogicActions {
    reloadAll: () => {
        value: true
    } // mcpDashboardOverviewLogic
    loadFacets: (_: void) => void
    loadFacetsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadFacetsSuccess: (
        facets: LeaderboardFacets,
        payload?: void
    ) => {
        facets: LeaderboardFacets
        payload?: void
    }
    loadReliabilityRows: (_: void) => void
    loadReliabilityRowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReliabilityRowsSuccess: (
        reliabilityRows: ReliabilityRow[],
        payload?: void
    ) => {
        reliabilityRows: ReliabilityRow[]
        payload?: void
    }
    setScoreboardMetric: (metric: ScoreboardMetric) => {
        metric: ScoreboardMetric
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpLeaderboardHomeLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        leaderboardLoading: (facetsLoading: boolean, reliabilityRowsLoading: boolean) => boolean
        labShares: (facets: LeaderboardFacets) => LabShare[]
        scoreboardShares: (
            scoreboardMetric: ScoreboardMetric,
            labShares: LabShare[],
            facets: LeaderboardFacets
        ) => LabShare[]
        modelSeries: (facets: LeaderboardFacets, bucketKeys: string[]) => ShareSeries[]
        labSeries: (facets: LeaderboardFacets, bucketKeys: string[]) => ShareSeries[]
        protocolVersionSeries: (facets: LeaderboardFacets, bucketKeys: string[]) => ShareSeries[]
        reliabilitySeries: (reliabilityRows: ReliabilityRow[], bucketKeys: string[]) => ReliabilitySeries
    }
}

export type mcpLeaderboardHomeLogicType = MakeLogicType<
    mcpLeaderboardHomeLogicValues,
    mcpLeaderboardHomeLogicActions,
    Record<string, any>,
    mcpLeaderboardHomeLogicMeta
>

export const mcpLeaderboardHomeLogic = kea<mcpLeaderboardHomeLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'leaderboardHome', 'mcpLeaderboardHomeLogic']),
    connect(() => ({
        values: [mcpDashboardOverviewLogic, ['queryFilters', 'interval', 'bucketKeys']],
        actions: [mcpDashboardOverviewLogic, ['reloadAll']],
    })),
    actions({
        setScoreboardMetric: (metric: ScoreboardMetric) => ({ metric }),
    }),
    reducers({
        scoreboardMetric: [
            'calls' as ScoreboardMetric,
            {
                setScoreboardMetric: (_, { metric }) => metric,
            },
        ],
    }),
    loaders(({ values }) => ({
        facets: [
            EMPTY_FACETS,
            {
                loadFacets: async (_: void, breakpoint): Promise<LeaderboardFacets> => {
                    const { queryFilters, interval } = values
                    const failedFacets: FacetKey[] = []
                    // A failed facet is reported and left out, so the other facets still render.
                    const run = async (facet: FacetKey, query: string): Promise<Row[]> => {
                        try {
                            return await runQuery(query, queryFilters)
                        } catch (error) {
                            failedFacets.push(facet)
                            posthog.captureException(error, { action: 'load-mcp-leaderboard-facet', facet })
                            return []
                        }
                    }
                    const [
                        model,
                        protocolVersion,
                        toolCategory,
                        tool,
                        intentSource,
                        errorType,
                        authMethod,
                        modelSource,
                        labUsers,
                        namedModelUsers,
                    ] = await Promise.all([
                        run('model', bucketedFacetQuery(MODEL_LABEL, interval)),
                        run('protocolVersion', bucketedFacetQuery(PROTOCOL_VERSION_LABEL, interval)),
                        run('toolCategory', windowFacetQuery(propertyLabel('$mcp_tool_category'))),
                        run('tool', windowFacetQuery(TOOL_LABEL)),
                        run('intentSource', windowFacetQuery(propertyLabel('$mcp_intent_source'))),
                        run('errorType', windowFacetQuery(propertyLabel('$mcp_error_type'), true)),
                        run('authMethod', windowFacetQuery(propertyLabel('$mcp_auth_method'))),
                        run('modelSource', windowFacetQuery(propertyLabel('$mcp_llm_model_source'))),
                        run('labUsers', labUsersQuery),
                        run('namedModelUsers', namedModelUsersQuery),
                    ])
                    breakpoint()
                    return {
                        model: toBucketedRows(model),
                        protocolVersion: toBucketedRows(protocolVersion),
                        toolCategory: toWindowRows(toolCategory),
                        tool: toWindowRows(tool),
                        intentSource: toWindowRows(intentSource),
                        errorType: toWindowRows(errorType),
                        authMethod: toWindowRows(authMethod),
                        modelSource: toWindowRows(modelSource),
                        labUsers: labUsers.map((r) => ({ lab: String(r[0]), users: Number(r[1]) })),
                        namedModelUsers: Number(namedModelUsers[0]?.[0] ?? 0),
                        failedFacets,
                    }
                },
            },
        ],
        reliabilityRows: [
            [] as ReliabilityRow[],
            {
                loadReliabilityRows: async (_: void, breakpoint): Promise<ReliabilityRow[]> => {
                    const rows = await runQuery(reliabilityQuery(values.interval), values.queryFilters)
                    breakpoint()
                    return toReliabilityRows(rows)
                },
            },
        ],
    })),
    selectors({
        leaderboardLoading: [
            (s) => [s.facetsLoading, s.reliabilityRowsLoading],
            (facetsLoading: boolean, reliabilityRowsLoading: boolean): boolean =>
                facetsLoading || reliabilityRowsLoading,
        ],
        labShares: [(s) => [s.facets], (facets: LeaderboardFacets): LabShare[] => buildLabShares(facets.model)],
        scoreboardShares: [
            (s) => [s.scoreboardMetric, s.labShares, s.facets],
            (metric: ScoreboardMetric, callShares: LabShare[], facets: LeaderboardFacets): LabShare[] =>
                metric === 'calls' ? callShares : buildLabUserShares(facets.labUsers, facets.namedModelUsers),
        ],
        modelSeries: [
            (s) => [s.facets, s.bucketKeys],
            (facets: LeaderboardFacets, bucketKeys: string[]): ShareSeries[] =>
                buildShareSeries(
                    facets.model,
                    bucketKeys,
                    (label) => (label === 'Unknown' ? null : label),
                    MODEL_SERIES_LIMIT
                ),
        ],
        labSeries: [
            (s) => [s.facets, s.bucketKeys],
            (facets: LeaderboardFacets, bucketKeys: string[]): ShareSeries[] =>
                buildShareSeries(
                    facets.model,
                    bucketKeys,
                    (label) => (label === 'Unknown' ? null : modelLab(label)),
                    MODEL_SERIES_LIMIT
                ),
        ],
        protocolVersionSeries: [
            (s) => [s.facets, s.bucketKeys],
            (facets: LeaderboardFacets, bucketKeys: string[]): ShareSeries[] =>
                buildShareSeries(facets.protocolVersion, bucketKeys, (label) => label, PROTOCOL_SERIES_LIMIT),
        ],
        reliabilitySeries: [
            (s) => [s.reliabilityRows, s.bucketKeys],
            (rows: ReliabilityRow[], bucketKeys: string[]): ReliabilitySeries =>
                buildReliabilitySeries(rows, bucketKeys),
        ],
    }),
    listeners(({ actions }) => ({
        reloadAll: () => {
            actions.loadFacets()
            actions.loadReliabilityRows()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadFacets()
        actions.loadReliabilityRows()
    }),
])
