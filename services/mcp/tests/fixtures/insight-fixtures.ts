// Real captured insight API responses, shared with the frontend's MSW fixtures
// (frontend/src/mocks/fixtures/api/projects/team_id/insights/). They are legacy
// `/api/insight/` payloads whose `result` field carries the same series items the
// modern `/query/` endpoint returns under `results` — the part the UI app type
// guards and visualizers inspect. `queryPayload` re-wraps a fixture's series as
// the `{ query, results }` payload the MCP UI apps receive.

import dataVisualizationHogQLJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json'
import funnelHistoricalTrendsJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'
import funnelTimeToConvertJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'
import funnelTopToBottomJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import funnelTopToBottomBreakdownJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'
import lifecycleJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import retentionJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/retention.json'
import stickinessJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import trendsLineJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import trendsLineBreakdownJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'
import trendsNumberJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'
import trendsPieJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import trendsWorldMapJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'
import userPathsJson from '../../../../frontend/src/mocks/fixtures/api/projects/team_id/insights/userPaths.json'

export const insightResults = {
    trendsLine: trendsLineJson.result,
    trendsLineBreakdown: trendsLineBreakdownJson.result,
    /** BoldNumber display — single series with `aggregated_value`. */
    trendsNumber: trendsNumberJson.result,
    trendsPie: trendsPieJson.result,
    trendsWorldMap: trendsWorldMapJson.result,
    /** Stickiness rows duck-type as trends (`data`/`labels`/`days`). */
    stickiness: stickinessJson.result,
    /** Funnel in trends visualization mode — time-series rows, not steps. */
    funnelHistoricalTrends: funnelHistoricalTrendsJson.result,
    funnelTopToBottom: funnelTopToBottomJson.result,
    /** Breakdown funnel — nested array of step arrays, one per breakdown. */
    funnelTopToBottomBreakdown: funnelTopToBottomBreakdownJson.result,
    /** Time-to-convert funnel — `{ average_conversion_time, bins }` object, no steps. */
    funnelTimeToConvert: funnelTimeToConvertJson.result,
    lifecycle: lifecycleJson.result,
    retention: retentionJson.result,
    userPaths: userPathsJson.result,
    /** The legacy serializer flattens `columns` to the top level; `/query/` nests them. */
    hogqlTable: { columns: dataVisualizationHogQLJson.columns, results: dataVisualizationHogQLJson.result },
} as const

export function queryPayload(results: unknown, kind?: string): { results: unknown; query?: { kind: string } } {
    return { results, ...(kind ? { query: { kind } } : {}) }
}
