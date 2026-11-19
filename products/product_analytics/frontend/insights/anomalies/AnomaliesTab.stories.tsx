import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { SavedInsightsTabs } from '~/types'

import type { AnomalySearchResponseApi, AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import insightsJson from '../savedInsights/__mocks__/insights.json'

const SEARCH_URL = '/api/projects/:team_id/signals/anomalies/search/'
const DAY_MS = 24 * 60 * 60 * 1000
const RANGE_START = Date.UTC(2026, 10, 3)

function dayIso(index: number): string {
    return new Date(RANGE_START + index * DAY_MS).toISOString().replace('.000Z', '+00:00')
}

function makeSeries(
    id: number,
    name: string,
    label: string,
    values: number[],
    flagged: number[],
    baselineRate: number | null
): AnomalySeriesApi {
    const flaggedDays = flagged.map(dayIso)
    return {
        insight_id: id,
        insight_name: name,
        insight_url: `http://localhost:8000/project/997/insights/insight${id}`,
        series_key: `${id}-${label}`,
        series_label: label,
        breakdown_value: null,
        interval: 'day',
        scored_buckets: values.length,
        flagged_buckets: flagged.length,
        anomaly_rate: flagged.length / values.length,
        expected_buckets: 14,
        coverage: values.length / 14,
        scored_through: dayIso(values.length - 1),
        baseline_rate: baselineRate,
        dashboards: [{ id: 1, name: 'Growth' }],
        first_flagged_bucket: flaggedDays[0] ?? null,
        last_flagged_bucket: flaggedDays.at(-1) ?? null,
        flagged_points: flagged
            .slice()
            .reverse()
            .map((index) => ({ bucket_start: dayIso(index), value: values[index], score: 4.2 })),
        points: values.map((value, index) => ({
            bucket_start: dayIso(index),
            value,
            flag: flagged.includes(index),
        })),
    }
}

function searchResponse(overrides: Partial<AnomalySearchResponseApi> = {}): AnomalySearchResponseApi {
    return {
        scoring_enabled: true,
        watched_insights: 140,
        insights_scored_in_range: 120,
        scored_days: 28,
        scored_history_ready: true,
        date_from: dayIso(0),
        date_to: dayIso(14),
        group_by: 'series',
        order: 'recent',
        series: [],
        insights: [],
        has_more: false,
        truncated: false,
        message: null,
        ...overrides,
    }
}

const FLAGGED_SERIES = [
    makeSeries(
        1,
        'Signups by referrer',
        'Organic search',
        [42, 40, 45, 43, 41, 44, 46, 43, 42, 45, 88, 97, 71, 44],
        [10, 11, 12],
        0.04
    ),
    makeSeries(2, 'Checkout started', 'Checkout started', [310, 305, 298, 312, 120, 115], [4, 5], 0),
]

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
    decorators: [mswDecorator({ get: { [SEARCH_URL]: searchResponse({ series: FLAGGED_SERIES, has_more: true }) } })],
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
