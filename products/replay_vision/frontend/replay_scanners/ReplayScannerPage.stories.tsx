import type { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { replayScannersStoryConfig } from '../__mocks__/replayScannersStoryConfig'
import {
    alice,
    bob,
    digestScoutConfig,
    freeCreditsUsedQuota,
    freeOnlyLimitReachedScanner,
    monitorOverviewScanner,
    monitorOverviewStats,
    overviewDecorator,
    scanner,
    summarizerScanner,
    summarizerStats,
} from '../__mocks__/replayScannersStoryFixtures'
import type { ObservationStatsApi } from '../generated/api.schemas'

const meta: Meta = {
    ...replayScannersStoryConfig,
    component: App,
    title: 'Scenes-App/Replay Vision',
}
export default meta

export const ScannerCreatorLostAccess: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        overviewDecorator(
            {
                ...summarizerScanner,
                enabled: false,
                disabled_reason: 'creator_lost_access',
                status: 'off',
                status_reason: 'creator_lost_access',
            },
            summarizerStats
        ),
    ],
}

// The Scouts tab offers each scanner type only the templates that fit it: root cause for a monitor.
export const MonitorScouts: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(monitorOverviewScanner.id)}?tab=scouts` },
    decorators: [overviewDecorator(monitorOverviewScanner, monitorOverviewStats)],
}

// A summarizer has no outcome to explain, so it gets weekly themes instead of root cause.
export const SummarizerScouts: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=scouts` },
}

// The scan-drought banner: current version 4 has no marker, and the sweep watermark sits past the
// last config change, so the page warns that the filters matched nothing. No other story renders it.
export const ScannerScanDrought: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/:id/': scanner({
                    id: summarizerScanner.id,
                    name: 'Confused checkout',
                    scanner_type: 'monitor',
                    scanner_config: { prompt: 'Did the user struggle?' },
                    scanner_version: 4,
                    sampling_rate: 0.1,
                    updated_at: '2026-05-10T00:00:00Z',
                    last_swept_at: '2026-05-12T00:00:00Z',
                    created_by: alice,
                }),
                '/api/projects/:team_id/vision/scanners/:id/observations/stats/': {
                    ...summarizerStats,
                    monitor: { yes_total: 12, no_total: 130, inconclusive_total: 0 },
                    labels: {
                        ...summarizerStats.labels,
                        version_markers: [
                            {
                                date: '2026-05-01',
                                version: 3,
                                prompt: 'Did the user struggle?',
                                scanner_config: { prompt: 'Did the user struggle?' },
                                scanner_type: 'monitor',
                                model: 'gemini-3.8-flash',
                                provider: 'google',
                                emits_signals: false,
                                query: null,
                                sampling_rate: 1,
                                up: 6,
                                down: 2,
                                total: 142,
                            },
                        ],
                    },
                } satisfies ObservationStatsApi,
            },
        }),
    ],
}

export const ScannerOnDemand: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=run` },
}

const trendScoutConfig = {
    ...digestScoutConfig,
    id: '00000000-0000-0000-0000-0000000000c2',
    skill_name: 'signals-scout-checkout-trend-watch',
    display_name: '',
    description: 'Watches for week-over-week movement in checkout friction themes.',
    owners: [bob],
    created_at: '2026-05-06T09:00:00Z',
}

const scoutReport = {
    report_id: '00000000-0000-0000-0000-0000000000d1',
    title: 'Daily digest confused checkout: 2026-05-12',
    summary: '**TL;DR:** Checkout friction held steady; coupon box confusion dominated.',
    skill_name: digestScoutConfig.skill_name,
    filed_at: '2026-05-12T09:00:00Z',
    charts: [],
    created_at: '2026-05-12T09:03:00Z',
    updated_at: '2026-05-12T09:03:00Z',
}

export const ScannerScouts: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=scouts`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/scout/configs/': [digestScoutConfig, trendScoutConfig],
                '/api/projects/:team_id/vision/scanners/:scannerId/scout_reports/': [scoutReport],
                '/api/projects/:team_id/llm_skills/name/:skillName/': {
                    body: 'Review new scanner observations and report changes in checkout friction.',
                },
            },
        }),
    ],
}

export const ScannerScoutsEmpty: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=scouts`,
    },
}

const metricAlert = {
    id: '00000000-0000-0000-0000-0000000000e1',
    scanner_id: summarizerScanner.id,
    name: 'Coupon friction spike',
    enabled: true,
    kind: 'metric',
    selection: {},
    metric: 'count',
    direction: 'above',
    threshold: 10,
    window_days: 1,
    check_interval_minutes: 60,
    state: 'not_firing',
    evaluation_periods: 1,
    notification_config: [],
    created_at: '2026-05-03T00:00:00Z',
    updated_at: '2026-05-03T00:00:00Z',
    created_by: alice,
}

const matchAlert = {
    ...metricAlert,
    id: '00000000-0000-0000-0000-0000000000e2',
    name: 'Any rage click observation',
    kind: 'match',
    metric: null,
    direction: null,
    threshold: null,
    state: 'firing',
    created_by: bob,
}

export const ScannerAlerts: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=alerts`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/alerts/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [metricAlert, matchAlert],
                },
            },
        }),
    ],
}

export const ScannerAlertsEmpty: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=alerts`,
    },
}

export const ScannerFreeCreditsStopping: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        overviewDecorator({ ...freeOnlyLimitReachedScanner, id: summarizerScanner.id }, summarizerStats),
        mswDecorator({ get: { '/api/projects/:team_id/vision/quota/': freeCreditsUsedQuota } }),
    ],
}

export const ScannerTurnedOffByFreeCredits: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        overviewDecorator(
            {
                ...freeOnlyLimitReachedScanner,
                id: summarizerScanner.id,
                enabled: false,
                disabled_reason: 'free_credits_used',
                status: 'off',
                status_reason: 'free_credits_used',
            },
            summarizerStats
        ),
        mswDecorator({ get: { '/api/projects/:team_id/vision/quota/': freeCreditsUsedQuota } }),
    ],
}
