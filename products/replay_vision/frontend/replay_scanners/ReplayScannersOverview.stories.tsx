import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { replayScannersStoryConfig } from '../__mocks__/replayScannersStoryConfig'
import {
    alice,
    bob,
    classifierOverviewScanner,
    classifierOverviewStats,
    digestScoutConfig,
    freeCreditsUsedQuota,
    freeOnlyLimitReachedScanner,
    monitorOverviewScanner,
    monitorOverviewStats,
    overviewDecorator,
    rootCauseFormScanner,
    scanner,
    scorerOverviewScanner,
    scorerOverviewStats,
    summarizerScanner,
    summarizerStats,
} from '../__mocks__/replayScannersStoryFixtures'
import type { ObservationStatsApi, ScannerSelfDrivingStatsApi } from '../generated/api.schemas'

const meta: Meta = {
    ...replayScannersStoryConfig,
    component: App,
    title: 'Scenes-App/Replay Vision',
}
export default meta

const activeSelfDrivingStats: ScannerSelfDrivingStatsApi = {
    signals_emitted: 64,
    reports_contributed: 9,
    prs_opened: 4,
    prs_merged: 2,
    reports: [
        {
            id: '00000000-0000-0000-0000-0000000000e1',
            title: 'Shipping step stalls after address reset',
            status: 'ready',
        },
        { id: '00000000-0000-0000-0000-0000000000e2', title: 'Coupon field rejects valid codes', status: 'ready' },
    ],
    pull_requests: [
        { url: 'https://github.com/example/shop/pull/412', merged: true },
        { url: 'https://github.com/example/shop/pull/409', merged: true },
        { url: 'https://github.com/example/shop/pull/405', merged: false },
        { url: 'https://github.com/example/shop/pull/398', merged: false },
    ],
}

export const SummarizerOverview: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
}

export const MonitorOverview: StoryObj = {
    parameters: { pageUrl: urls.replayVision(monitorOverviewScanner.id) },
    decorators: [overviewDecorator(monitorOverviewScanner, monitorOverviewStats, activeSelfDrivingStats)],
}

// Expensive filters stretch the sweep to its hourly ceiling, so the status strip reports it as throttled.
export const ScannerStatusThrottled: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        overviewDecorator(
            { ...summarizerScanner, sweep_throttle_factor: 12, sweep_interval_minutes: 60 },
            summarizerStats
        ),
    ],
}

export const ScannerCreatorLostAccess: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        overviewDecorator(
            { ...summarizerScanner, enabled: false, disabled_reason: 'creator_lost_access' },
            summarizerStats
        ),
    ],
}

export const ScannerNoRecordings: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        overviewDecorator(summarizerScanner, summarizerStats),
        mswDecorator({
            get: { '/api/environments/:team_id/session_recordings/': { results: [], has_next: false } },
        }),
    ],
}

export const ScannerTurnedOff: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [overviewDecorator({ ...summarizerScanner, enabled: false }, summarizerStats)],
}

// Once a scanner has enough observations, the overview offers a dashboard for it.
export const MonitorOverviewDashboardOffer: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(monitorOverviewScanner.id),
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_SCANNER_DASHBOARD]: true },
    },
    decorators: [overviewDecorator({ ...monitorOverviewScanner, dashboard_suggested: true }, monitorOverviewStats)],
}

export const ClassifierOverview: StoryObj = {
    parameters: { pageUrl: urls.replayVision(classifierOverviewScanner.id) },
    decorators: [overviewDecorator(classifierOverviewScanner, classifierOverviewStats)],
}

export const ScorerOverview: StoryObj = {
    parameters: { pageUrl: urls.replayVision(scorerOverviewScanner.id) },
    decorators: [overviewDecorator(scorerOverviewScanner, scorerOverviewStats)],
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

// The root cause prompt under the findings opens the create form in place.
export const MonitorRootCauseScoutForm: StoryObj = {
    parameters: { pageUrl: urls.replayVision(rootCauseFormScanner.id) },
    decorators: [overviewDecorator(rootCauseFormScanner, monitorOverviewStats)],
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Add scout'))
        await within(document.body).findByText('New scout: root cause')
    },
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

// A realistic multi-section digest in the Overview's side column, so its clamp and "Show full report" render.
export const MonitorOverviewWithScoutReport: StoryObj = {
    parameters: { pageUrl: urls.replayVision(monitorOverviewScanner.id) },
    decorators: [
        overviewDecorator(monitorOverviewScanner, monitorOverviewStats, activeSelfDrivingStats),
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/scout/configs/': [
                    { ...digestScoutConfig, source_id: monitorOverviewScanner.id },
                ],
                '/api/projects/:team_id/vision/scanners/:scannerId/scout_reports/': [
                    {
                        ...scoutReport,
                        summary: [
                            '**TL;DR:** Yes verdicts rose from 22% to 27% this week, driven by the new shipping step.',
                            '',
                            '**What changed**',
                            '',
                            '[Yes verdicts by day](chart:yes-by-day)',
                            '',
                            '- 14 sessions stalled on the shipping options screen after the address form reset.',
                            '- Coupon errors fell to 3 sessions, down from 11 before the validation fix.',
                            '- Mobile Safari accounts for 9 of the 14 shipping stalls.',
                            '',
                            '**Worth a look**',
                            '- The address form clears the postcode when the user goes back a step.',
                            '- Two sessions retried payment four times before giving up.',
                            '',
                            '**Unchanged**',
                            '- Card declines stayed flat at about 2% of checkouts.',
                        ].join('\n'),
                        charts: [
                            {
                                chart_id: 'yes-by-day',
                                title: 'Yes verdicts by day',
                                caption: 'The rise starts the day the new shipping step shipped.',
                                query: {
                                    kind: 'InsightVizNode',
                                    source: {
                                        kind: 'TrendsQuery',
                                        series: [
                                            { kind: 'EventsNode', event: '$recording_observed', name: 'Yes verdicts' },
                                        ],
                                        dateRange: { date_from: '2026-04-29', date_to: '2026-05-12' },
                                    },
                                },
                            },
                            {
                                chart_id: 'stalls-by-browser',
                                title: 'Shipping stalls by browser',
                                query: {
                                    kind: 'InsightVizNode',
                                    source: {
                                        kind: 'TrendsQuery',
                                        series: [{ kind: 'EventsNode', event: '$recording_observed', name: 'Stalls' }],
                                        trendsFilter: { display: 'ActionsBarValue' },
                                        dateRange: { date_from: '2026-04-29', date_to: '2026-05-12' },
                                    },
                                },
                            },
                        ],
                    },
                ],
            },
        }),
    ],
}

const rootCauseScoutConfig = {
    ...digestScoutConfig,
    id: '00000000-0000-0000-0000-0000000000c3',
    skill_name: 'signals-scout-confused-checkout-root-cause',
    display_name: 'Confused checkout root cause',
    source_id: monitorOverviewScanner.id,
    run_cron_schedule: '0 9 * * 1',
}

const rootCauseReport = {
    ...scoutReport,
    report_id: '00000000-0000-0000-0000-0000000000d2',
    title: 'Root cause confused checkout: 2026-05-11',
    skill_name: rootCauseScoutConfig.skill_name,
    filed_at: '2026-05-11T09:00:00Z',
    summary: [
        'Root cause for Confused checkout: 212 sessions answered yes vs 1,340 answered no, last 30 days',
        '',
        '**TL;DR:** Two causes explain 61% of flagged sessions: the shipping options reset after an address edit (38%), and a coupon error rendered below the fold on mobile (23%).',
        '',
        '## Shipping options reset after an address edit',
        '',
        '- 81 sessions, 38% of the bucket, 4% of the contrast.',
    ].join('\n'),
}

const rootCauseMocks = mswDecorator({
    get: {
        '/api/projects/:team_id/signals/scout/configs/': [rootCauseScoutConfig],
        '/api/projects/:team_id/vision/scanners/:scannerId/scout_reports/': [rootCauseReport],
    },
})

// A scanner with a root cause scout no longer gets the offer; its reports show in the scout card.
export const MonitorOverviewWithRootCause: StoryObj = {
    parameters: { pageUrl: urls.replayVision(monitorOverviewScanner.id) },
    decorators: [overviewDecorator(monitorOverviewScanner, monitorOverviewStats), rootCauseMocks],
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

// The status strip explains the free-credits stop and how to keep scanning.
export const ScannerOverviewFreeCreditsUsed: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        overviewDecorator({ ...freeOnlyLimitReachedScanner, id: summarizerScanner.id }, summarizerStats),
        mswDecorator({ get: { '/api/projects/:team_id/vision/quota/': freeCreditsUsedQuota } }),
    ],
}

export const ScannerOverviewTurnedOffByFreeCredits: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        overviewDecorator(
            {
                ...freeOnlyLimitReachedScanner,
                id: summarizerScanner.id,
                enabled: false,
                disabled_reason: 'free_credits_used',
            },
            summarizerStats
        ),
        mswDecorator({ get: { '/api/projects/:team_id/vision/quota/': freeCreditsUsedQuota } }),
    ],
}
