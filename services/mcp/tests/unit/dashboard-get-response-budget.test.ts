import { describe, expect, it, vi } from 'vitest'

import { estimateTokens } from '@/lib/estimate-tokens'
import { formatResponse } from '@/lib/response'
import { GENERATED_TOOLS } from '@/tools/generated/dashboards'
import type { Context } from '@/tools/types'

/**
 * An agent that reads a dashboard over MCP has to fit the whole response in one tool result.
 * A dashboard of this size is ordinary, so the ceiling here is the size that keeps the
 * list-to-detail flow usable — not the size the payload happens to be today.
 */
const TOKEN_BUDGET = 10_000

const TILE_COUNT = 11

/** The `UserBasic` keys an agent cannot act on. Name and email stay. */
const STRIPPED_USER_FIELDS = ['uuid', 'distinct_id', 'is_email_verified', 'hedgehog_config']

function createUser(id: number, firstName: string, lastName: string): Record<string, unknown> {
    return {
        id,
        uuid: `00000000-0000-4000-8000-0000000000${id}`,
        distinct_id: `distinct-id-for-user-${id}`,
        first_name: firstName,
        last_name: lastName,
        email: `${firstName.toLowerCase()}@example.com`,
        is_email_verified: true,
        hedgehog_config: {
            use_as_profile: false,
            color: 'invert-hue',
            accessories: ['flag', 'sunglasses', 'parrot'],
            skin: 'default',
        },
        role_at_organization: null,
    }
}

/**
 * A trends query with every optional field the serializer emits. The explicit `null`s are the
 * point of the fixture: they are what the response used to spend most of its size on.
 */
function createTileQuery(): Record<string, unknown> {
    return {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            aggregation_group_type_index: null,
            breakdownFilter: {
                breakdown: 'tool',
                breakdown_group_type_index: null,
                breakdown_hide_other_aggregation: null,
                breakdown_histogram_bin_count: null,
                breakdown_limit: 10,
                breakdown_normalize_url: null,
                breakdown_path_cleaning: null,
                breakdown_type: 'event',
                breakdowns: null,
            },
            calendarHeatmapFilter: null,
            compareFilter: null,
            conversionGoal: null,
            dataColorTheme: null,
            dateRange: {
                date_from: '-90d',
                date_to: null,
                daysOfWeek: null,
                excludeIncompletePeriods: false,
                explicitDate: false,
            },
            filterTestAccounts: false,
            interval: 'week',
            modifiers: null,
            properties: { type: 'AND', values: [] },
            response: null,
            samplingFactor: null,
            series: [
                {
                    kind: 'EventsNode',
                    custom_name: 'Calls',
                    event: 'widget opened',
                    fixedProperties: null,
                    limit: null,
                    math: 'total',
                    math_group_type_index: null,
                    math_hogql: null,
                    math_multiplier: null,
                    math_property: null,
                    math_property_revenue_currency: null,
                    math_property_type: null,
                    name: null,
                    optionalInFunnel: null,
                    orderBy: null,
                    properties: null,
                    response: null,
                    version: null,
                },
            ],
            tags: null,
            trendsFilter: {
                aggregationAxisFormat: 'numeric',
                aggregationAxisPostfix: null,
                aggregationAxisPrefix: null,
                breakdown_histogram_bin_count: null,
                chartStyle: null,
                confidenceLevel: null,
                decimalPlaces: null,
                detailedResultsAggregationType: null,
                display: 'ActionsLineGraph',
                excludeBoxPlotOutliers: true,
                formula: null,
                formulaNodes: null,
                formulas: null,
                goalLines: null,
                hiddenLegendIndexes: null,
                hideWeekends: false,
                legendPosition: 'bottom',
                metricChangeDecreaseColor: null,
                metricChangeIncreaseColor: null,
                metricColorByDirection: false,
                metricLineDecreaseColor: null,
                metricLineIncreaseColor: null,
                metricShowChange: true,
                metricSummary: 'total',
                minDecimalPlaces: null,
                movingAverageIntervals: null,
                resultCustomizationBy: 'value',
                resultCustomizations: null,
                showAlertThresholdLines: false,
                showAnnotations: true,
                showConfidenceIntervals: null,
                showLabelsOnSeries: null,
                showLegend: true,
                showMovingAverage: null,
                showMultipleYAxes: false,
                showPercentStackView: false,
                showTrendLines: null,
                showValuesOnSeries: false,
                smoothingIntervals: 1,
                stackBreakdownValues: false,
                xAxisLabel: null,
                yAxisLabel: null,
                yAxisMax: null,
                yAxisMin: null,
                yAxisScaleType: 'linear',
                yAxisStartAtZero: true,
            },
            version: 4,
        },
    }
}

function createDashboardResponse(): Record<string, unknown> {
    const dashboardFilters = {
        properties: [{ key: 'client_name', type: 'event', value: 'is_set', operator: 'is_set' }],
    }
    return {
        id: 42,
        name: 'Widget adoption',
        description: 'Widget usage over time',
        pinned: true,
        created_at: '2026-02-18T18:28:34.858807Z',
        created_by: createUser(1, 'Ada', 'Lovelace'),
        last_accessed_at: '2026-09-10T12:41:12.137521Z',
        last_viewed_at: null,
        filters: dashboardFilters,
        variables: {},
        team_id: 7,
        tags: ['widgets'],
        tiles: Array.from({ length: TILE_COUNT }, (_, index) => ({
            id: 1000 + index,
            insight: {
                id: 2000 + index,
                short_id: `short${index}`,
                name: `Widget metric ${index}`,
                derived_name: null,
                query: createTileQuery(),
                description: `What widget metric ${index} measures`,
                created_at: '2026-02-18T18:28:57.827410Z',
                created_by: createUser(1, 'Ada', 'Lovelace'),
                updated_at: '2026-06-19T07:10:12.182364Z',
                favorited: false,
                saved: true,
                last_modified_at: '2026-06-19T07:10:12.181366Z',
                last_modified_by: createUser(2, 'Grace', 'Hopper'),
                last_refresh: null,
                is_cached: false,
                filter_override_context: {
                    dashboard: dashboardFilters,
                    tile: null,
                    overridden_dashboard: null,
                },
                last_viewed_at: null,
                tags: ['widgets'],
            },
            text: null,
            widget: null,
            layouts: { sm: { h: 5, i: `${1000 + index}`, w: 6, x: 0, y: index * 5, minH: 2, minW: 2 } },
            filters_overrides: {},
            order: index,
            last_refresh: null,
            is_cached: false,
        })),
    }
}

type TileContent = Record<string, unknown> & {
    created_by: Record<string, unknown>
    last_modified_by: Record<string, unknown>
}

/**
 * A dashboard that mixes tile types. The all-insight fixture leaves `text` and `widget` null on
 * every tile, and `strip_nulls` then removes both keys, so it never reaches what they nest.
 */
function createMixedDashboardResponse(): Record<string, unknown> {
    const base = createDashboardResponse()
    const tileBackReference = [{ id: 1100, dashboard_id: 42, deleted: false }]
    return {
        ...base,
        tiles: [
            (base.tiles as Record<string, unknown>[])[0]!,
            {
                id: 1100,
                insight: null,
                text: {
                    id: 300,
                    body: '## Adoption\n\nThe charts below track the widgets released this quarter.',
                    created_by: createUser(1, 'Ada', 'Lovelace'),
                    last_modified_at: '2026-06-19T07:10:12.181366Z',
                    last_modified_by: createUser(2, 'Grace', 'Hopper'),
                    team: 7,
                    dashboard_tiles: tileBackReference,
                },
                widget: null,
                layouts: { sm: { h: 2, i: '1100', w: 6, x: 0, y: 55, minH: 2, minW: 2 } },
                filters_overrides: {},
                order: TILE_COUNT,
                last_refresh: null,
                is_cached: false,
            },
            {
                id: 1101,
                insight: null,
                text: null,
                widget: {
                    id: '00000000-0000-4000-8000-000000000abc',
                    widget_type: 'error_tracking_list',
                    name: 'Widget errors',
                    description: 'Open issues raised by the widget surface',
                    config: { limit: 5, order_by: null },
                    created_by: createUser(1, 'Ada', 'Lovelace'),
                    last_modified_at: '2026-06-19T07:10:12.181366Z',
                    last_modified_by: createUser(2, 'Grace', 'Hopper'),
                    team: 7,
                    dashboard_tiles: tileBackReference,
                },
                layouts: { sm: { h: 5, i: '1101', w: 6, x: 0, y: 57, minH: 2, minW: 2 } },
                filters_overrides: {},
                order: TILE_COUNT + 1,
                last_refresh: null,
                is_cached: false,
            },
        ],
    }
}

function createMockContext(result: Record<string, unknown>): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue(result),
            getProjectBaseUrl: () => 'https://us.posthog.com/project/7',
        },
        stateManager: { getProjectId: async () => 7 },
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
}

describe('dashboard-get response budget', () => {
    const tool = GENERATED_TOOLS['dashboard-get']!()

    async function shapeDashboard(): Promise<Record<string, unknown>> {
        return (await tool.handler(createMockContext(createDashboardResponse()), {
            id: 42,
        })) as unknown as Record<string, unknown>
    }

    it(`keeps a ${TILE_COUNT}-tile dashboard within the response budget`, async () => {
        const shaped = await shapeDashboard()

        expect(estimateTokens(formatResponse(shaped))).toBeLessThan(TOKEN_BUDGET)
    })

    it('keeps the tiles, queries and creators an agent needs', async () => {
        const shaped = await shapeDashboard()
        const tiles = shaped.tiles as { id: number; insight: Record<string, unknown> }[]

        expect(tiles).toHaveLength(TILE_COUNT)
        for (const tile of tiles) {
            expect(tile.insight.short_id).toBeTruthy()
            expect((tile.insight.query as { source: { kind: string } }).source.kind).toBe('TrendsQuery')
        }

        const creator = tiles[0]!.insight.created_by as Record<string, unknown>
        expect(creator.email).toBe('ada@example.com')
        for (const field of STRIPPED_USER_FIELDS) {
            expect(creator).not.toHaveProperty(field)
        }
        // The dashboard's own `filters` already carries what this per-tile copy repeated.
        expect(tiles[0]!.insight).not.toHaveProperty('filter_override_context')
        expect(shaped.filters).toBeTruthy()
    })

    it('strips the same creator metadata from text and widget tiles', async () => {
        const shaped = (await tool.handler(createMockContext(createMixedDashboardResponse()), {
            id: 42,
        })) as unknown as Record<string, unknown>
        const tiles = shaped.tiles as { text?: TileContent; widget?: TileContent }[]
        const textTile = tiles[1]!.text!
        const widgetTile = tiles[2]!.widget!

        expect(textTile.body as string).toContain('The charts below track')
        expect(widgetTile.name).toBe('Widget errors')
        expect(widgetTile.config).toEqual({ limit: 5 })

        for (const tile of [textTile, widgetTile]) {
            expect(tile.created_by.email).toBe('ada@example.com')
            expect(tile.last_modified_by.first_name).toBe('Grace')
            for (const field of STRIPPED_USER_FIELDS) {
                expect(tile.created_by).not.toHaveProperty(field)
                expect(tile.last_modified_by).not.toHaveProperty(field)
            }
            expect(tile).not.toHaveProperty('dashboard_tiles')
        }
    })

    it('carries no null-valued keys, which the serializer emits for every unset field', async () => {
        const shaped = await shapeDashboard()

        expect(JSON.stringify(shaped)).not.toContain(':null')
    })
})
