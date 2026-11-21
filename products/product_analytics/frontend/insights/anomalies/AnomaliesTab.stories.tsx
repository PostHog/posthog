import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { SavedInsightsTabs } from '~/types'

import type {
    AnomalyPointsResponseApi,
    AnomalySearchResponseApi,
    AnomalySeriesApi,
    AnomalySeriesPointApi,
} from 'products/signals/frontend/generated/api.schemas'

import insightsJson from '../savedInsights/__mocks__/insights.json'

const SEARCH_URL = '/api/projects/:team_id/signals/anomalies/search/'
const POINTS_URL = '/api/projects/:team_id/signals/anomalies/points/'
const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * HOUR_MS
const NOW = Date.UTC(2026, 10, 17)
const FLAG_FROM = NOW - 3 * DAY_MS

function iso(time: number): string {
    return new Date(time).toISOString().replace('.000Z', '+00:00')
}

interface StorySeries {
    row: AnomalySeriesApi
    chartFrom: string
    points: AnomalySeriesPointApi[]
}

// `values` and `flagged` count buckets back from the newest completed one, so the last value is the newest.
function makeSeries(
    id: number,
    name: string,
    label: string,
    interval: 'hour' | 'day',
    values: number[],
    flaggedAgo: number[]
): StorySeries {
    const step = interval === 'hour' ? HOUR_MS : DAY_MS
    const points = values.map((value, index) => {
        const ago = values.length - index
        return { bucket_start: iso(NOW - ago * step), value, flag: flaggedAgo.includes(ago) }
    })
    const inFlagWindow = points.filter((point) => Date.parse(point.bucket_start) >= FLAG_FROM)
    const flagged = inFlagWindow.filter((point) => point.flag)
    return {
        chartFrom: iso(NOW - (interval === 'hour' ? 7 : 28) * DAY_MS),
        points,
        row: {
            insight_id: id,
            insight_name: name,
            insight_url: `http://localhost:8000/project/997/insights/insight${id}`,
            series_key: `${id}-${label}`,
            series_label: label,
            breakdown_value: null,
            interval,
            scored_buckets: inFlagWindow.length,
            flagged_buckets: flagged.length,
            anomaly_rate: flagged.length / inFlagWindow.length,
            expected_buckets: inFlagWindow.length,
            coverage: 1,
            scored_through: points[points.length - 1].bucket_start,
            dashboards: [{ id: 1, name: 'Growth' }],
            first_flagged_bucket: flagged[0]?.bucket_start ?? null,
            last_flagged_bucket: flagged.at(-1)?.bucket_start ?? null,
            flagged_points: flagged
                .slice()
                .reverse()
                .map((point) => ({ bucket_start: point.bucket_start, value: point.value, score: 4.2 })),
        },
    }
}

function searchResponse(overrides: Partial<AnomalySearchResponseApi> = {}): AnomalySearchResponseApi {
    return {
        scoring_enabled: true,
        watched_insights: 140,
        insights_scored_in_range: 120,
        scored_days: 28,
        scored_history_ready: true,
        date_from: iso(FLAG_FROM),
        date_to: iso(NOW),
        group_by: 'series',
        order: 'recent',
        max_anomaly_rate: 0.1,
        hidden_series: 0,
        series: [],
        insights: [],
        has_more: false,
        truncated: false,
        series_capped: false,
        message: null,
        ...overrides,
    }
}

// 28 days with lower weekend values. `overrides` sets a value by how many days ago its bucket is.
function dailyValues(weekday: number, weekend: number, overrides: Record<number, number> = {}): number[] {
    return Array.from({ length: 28 }, (_, index) => {
        const ago = 28 - index
        const day = new Date(NOW - ago * DAY_MS).getUTCDay()
        return overrides[ago] ?? (day === 0 || day === 6 ? weekend : weekday)
    })
}

const FLAGGED_SERIES = [
    makeSeries(
        1,
        'Signups by referrer',
        'Organic search',
        'day',
        dailyValues(44, 30, { 10: 79, 3: 88, 2: 97 }),
        [10, 3, 2]
    ),
    makeSeries(1, 'Signups by referrer', 'Paid social', 'day', dailyValues(21, 15, { 3: 60, 2: 64 }), [3, 2]),
    makeSeries(1, 'Signups by referrer', 'Newsletter', 'day', dailyValues(8, 5, { 2: 30 }), [2]),
    makeSeries(1, 'Signups by referrer', 'Direct', 'day', dailyValues(64, 50, { 17: 20, 3: 30, 2: 28 }), [17, 3, 2]),
    makeSeries(1, 'Signups by referrer', 'Partners', 'day', dailyValues(5, 3, { 2: 18 }), [2]),
    makeSeries(
        2,
        'Checkout started',
        'Checkout started',
        'hour',
        Array.from(
            { length: 7 * 24 },
            (_, index) => 300 + 40 * Math.sin((index / 24) * 2 * Math.PI) - (index > 150 ? 180 : 0)
        ),
        [17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 120]
    ),
]

function pointsResponse(): AnomalyPointsResponseApi {
    return {
        date_to: iso(NOW),
        series: FLAGGED_SERIES.map(({ row, chartFrom, points }) => ({
            insight_id: row.insight_id,
            series_key: row.series_key,
            interval: row.interval,
            date_from: chartFrom,
            points,
        })),
    }
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Saved Insights/Anomalies',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-11-17',
        pageUrl: `${urls.savedInsights()}?tab=${SavedInsightsTabs.Anomalies}`,
        featureFlags: { [FEATURE_FLAGS.ANOMALIES_TAB]: true },
        testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                // One saved insight, so the scene shows its tabs rather than the first-run screen.
                '/api/environments/:team_id/insights': toPaginatedResponse(insightsJson.results.slice(0, 1)),
                '/api/projects/:team_id/insights/': toPaginatedResponse(insightsJson.results.slice(0, 1)),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const FlaggedSeries: Story = {
    parameters: {
        testOptions: {
            snapshotBrowsers: [],
            waitForLoadersToDisappear: true,
            waitForSelector: '[data-attr="anomalies-tab-row-chart"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                [SEARCH_URL]: searchResponse({
                    series: FLAGGED_SERIES.map(({ row }) => row),
                    has_more: true,
                    hidden_series: 3,
                }),
            },
            post: { [POINTS_URL]: pointsResponse() },
        }),
    ],
}

export const SeriesCapped: Story = {
    parameters: {
        testOptions: {
            snapshotBrowsers: [],
            waitForLoadersToDisappear: true,
            waitForSelector: '[data-attr="anomalies-tab-series-capped"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                [SEARCH_URL]: searchResponse({
                    series: FLAGGED_SERIES.map(({ row }) => row),
                    truncated: true,
                    series_capped: true,
                }),
            },
            post: { [POINTS_URL]: pointsResponse() },
        }),
    ],
}

export const NothingFlagged: Story = {
    decorators: [mswDecorator({ get: { [SEARCH_URL]: searchResponse() } })],
}

export const HistoryNotReady: Story = {
    decorators: [
        mswDecorator({
            get: { [SEARCH_URL]: searchResponse({ scored_days: 5, scored_history_ready: false }) },
        }),
    ],
}

export const ScoringOff: Story = {
    decorators: [
        mswDecorator({
            get: {
                [SEARCH_URL]: searchResponse({
                    scoring_enabled: false,
                    watched_insights: 0,
                    insights_scored_in_range: 0,
                    scored_days: 0,
                    scored_history_ready: false,
                    message: 'Anomaly scoring is not enabled for this project, so no insight is scored.',
                }),
            },
        }),
    ],
}

export const NotAvailable: Story = {
    decorators: [mswDecorator({ get: { [SEARCH_URL]: () => [404, { detail: 'Not found.' }] } })],
}
