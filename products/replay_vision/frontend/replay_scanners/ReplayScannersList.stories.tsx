import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { dayjs } from 'lib/dayjs'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { StartupProgramLabel } from '~/types'

import { replayScannersStoryConfig } from '../__mocks__/replayScannersStoryConfig'
import {
    freeCreditsUsedQuota,
    freeOnlyLimitReachedScanner,
    observation,
    quota,
    scannerStats,
    scanners,
    summarizerScanner,
} from '../__mocks__/replayScannersStoryFixtures'
import type { ScannerStatsResponseApi } from '../generated/api.schemas'

const meta: Meta = {
    ...replayScannersStoryConfig,
    component: App,
    title: 'Scenes-App/Replay Vision',
}
export default meta

export const ScannersList: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision()}?tab=scanners` },
}

export const ScannersListReplayOff: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision()}?tab=scanners` },
    decorators: [
        (Story) => {
            const { loadCurrentTeamSuccess } = useActions(teamLogic)
            useDelayedOnMountEffect(() => {
                loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: false })
            })
            return <Story />
        },
    ],
}

// A project that has never created a scanner: the surface of the empty-state experiment.
const emptyProjectDecorators = [
    mswDecorator({
        get: {
            '/api/projects/:team_id/vision/scanners/': { count: 0, next: null, previous: null, results: [] },
            '/api/projects/:team_id/vision/scanners/stats/': {
                total: 0,
                enabled: 0,
                by_type: {
                    monitor: { enabled: 0, total: 0 },
                    classifier: { enabled: 0, total: 0 },
                    scorer: { enabled: 0, total: 0 },
                    summarizer: { enabled: 0, total: 0 },
                    experiment: { enabled: 0, total: 0 },
                },
            } satisfies ScannerStatsResponseApi,
            '/api/projects/:team_id/vision/scanners/creators/': { creators: [] },
        },
    }),
]

export const ScannersListEmpty: StoryObj = {
    decorators: emptyProjectDecorators,
    parameters: { pageUrl: `${urls.replayVision()}?tab=scanners` },
}

export const UsageTab: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision()}?tab=usage` },
}

// The other sessions in the first embedding card's feed group, as the scanner's observation list returns them.
const checkoutGroupMembers = [
    {
        email: 'bob@example.com',
        reasoning: 'The card form rejected a valid card twice, then the user switched cards.',
        hoursAgo: 2,
        keyMomentMs: 98000,
    },
    {
        email: 'carol@example.com',
        reasoning: 'A valid card failed with a generic error before the user gave up.',
        hoursAgo: 5,
        keyMomentMs: 212000,
    },
    {
        email: 'dan@example.com',
        reasoning: 'The card form cleared itself after a failed charge and the user retyped it.',
        hoursAgo: 9,
        keyMomentMs: 41000,
    },
    {
        email: 'erin@example.com',
        reasoning: 'The payment step rejected the card and the user left checkout.',
        hoursAgo: 26,
        keyMomentMs: 305000,
    },
    {
        email: 'frank@example.com',
        reasoning: 'The user retried a declined card three times in a row.',
        hoursAgo: 50,
        keyMomentMs: null,
    },
].map(({ email, reasoning, hoursAgo, keyMomentMs }, index) =>
    observation({
        id: `00000000-0000-0000-0000-0000000000c${index}`,
        scanner_id: scanners.results[0].id,
        recording_subject_email: email,
        created_at: dayjs('2026-05-11T09:00:00Z').subtract(hoursAgo, 'hour').toISOString(),
        scanner_snapshot: { ...observation().scanner_snapshot!, name: 'Confused checkout', scanner_type: 'monitor' },
        scanner_result: {
            model_output: {
                scanner_type: 'monitor',
                verdict: 'yes',
                confidence: 0.9,
                reasoning,
                ...(keyMomentMs !== null ? { key_moment_ms: keyMomentMs } : {}),
            },
            signals_count: 0,
        },
    })
)

// The home page lands on the Highlights feed. There is one pick per scanner type, so each answer label shows. Each pick
// names its category, and the first stands for seven similar sessions. The viewer created one scanner, so the feed
// offers the scope tabs.
export const HomeHighlightFeed: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/': {
                    ...scanners,
                    results: scanners.results.map((item, index) =>
                        index === 0
                            ? { ...item, created_by: { ...MOCK_DEFAULT_BASIC_USER, id: MOCK_DEFAULT_USER.id } }
                            : item
                    ),
                },
                '/api/projects/:team_id/vision/scanners/:id/observations/': {
                    // The group holds seven other sessions, so the preview of five ends with a link to the rest.
                    count: 7,
                    next: null,
                    previous: null,
                    results: checkoutGroupMembers,
                },
                '/api/projects/:team_id/vision/scanners/highlight_feed/': {
                    has_more: false,
                    results: [
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000a1',
                                prompt_question: 'Did the user hesitate at checkout?',
                                prompt_valence: 'bad',
                                scanner_id: scanners.results[0].id,
                                scanner_snapshot: {
                                    name: 'Confused checkout',
                                    scanner_type: 'monitor',
                                    scanner_version: 1,
                                    model: 'gemini-3.8-flash',
                                    provider: 'google',
                                    emits_signals: true,
                                    scanner_config: { prompt: 'Did the user hesitate at checkout?' },
                                },
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'monitor',
                                        verdict: 'yes',
                                        confidence: 0.92,
                                        reasoning:
                                            'The card form rejected a valid card three times before the user left. They retried with the same card, opened the help chat to ask why it was declined, then closed the tab without paying.',
                                        key_moment_ms: 154000,
                                    },
                                    signals_count: 0,
                                },
                                viewed: false,
                            }),
                            reason: {
                                kind: 'embedding_pick',
                                watch_category: 'failure',
                                similar_count: 7,
                                affected_people: 6,
                            },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000a2',
                                prompt_question: 'What happened in this session?',
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'summarizer',
                                        confidence: 0.8,
                                        title: 'Plan limit blocked an export',
                                        summary: 'The export stopped at the plan limit and the user opened billing.',
                                        chapters: [
                                            { kind: 'activity', start_ms: 0, end_ms: 42000, title: 'Built a report' },
                                            {
                                                kind: 'activity',
                                                start_ms: 42000,
                                                end_ms: 97000,
                                                title: 'Hit the plan limit',
                                            },
                                            {
                                                kind: 'activity',
                                                start_ms: 97000,
                                                end_ms: 130000,
                                                title: 'Opened billing',
                                            },
                                        ],
                                    },
                                    signals_count: 0,
                                },
                                media: [0, 1, 2].map((position) => ({
                                    id: `00000000-0000-0000-0000-0000000000c${position}`,
                                    kind: 'chapter',
                                    position,
                                    asset_id: 4100 + position,
                                    video_start_ms: position * 40000,
                                })),
                                viewed: true,
                            }),
                            reason: { kind: 'embedding_pick', watch_category: 'revenue', similar_count: 0 },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000a3',
                                prompt_question: 'Which frustration patterns appear in this session?',
                                scanner_id: scanners.results[1].id,
                                scanner_snapshot: {
                                    name: 'Frustration tags',
                                    scanner_type: 'classifier',
                                    scanner_version: 1,
                                    model: 'gemini-3.8-flash',
                                    provider: 'google',
                                    emits_signals: false,
                                    scanner_config: {
                                        prompt: 'Tag this session.',
                                        tags: ['rage-click', 'dead-end'],
                                        multi_label: true,
                                    },
                                },
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'classifier',
                                        tags: ['rage-click', 'dead-end'],
                                        confidence: 0.64,
                                        reasoning:
                                            'The user clicked the disabled Save button eleven times. The settings page gave no reason why, so they left for the docs.',
                                        key_moment_ms: 61000,
                                    },
                                    signals_count: 0,
                                },
                                viewed: true,
                            }),
                            reason: { kind: 'embedding_pick', watch_category: 'struggle', similar_count: 3 },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000a4',
                                prompt_question: 'How strong is the buying intent in this session?',
                                prompt_valence: 'good',
                                scanner_id: scanners.results[3].id,
                                scanner_snapshot: {
                                    name: 'Intent score',
                                    scanner_type: 'scorer',
                                    scanner_version: 1,
                                    model: 'gemini-3.8-flash',
                                    provider: 'google',
                                    emits_signals: false,
                                    scanner_config: { prompt: 'Score this session.', scale: { min: 0, max: 10 } },
                                },
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'scorer',
                                        score: 9,
                                        confidence: 0.88,
                                        reasoning:
                                            'The user compared plans twice and opened the billing page. They invited a teammate before checking out.',
                                        key_moment_ms: 95000,
                                    },
                                    signals_count: 0,
                                },
                                viewed: true,
                            }),
                            reason: { kind: 'embedding_pick', watch_category: 'revenue', similar_count: 0 },
                        },
                    ],
                },
            },
        }),
    ],
}

// A quiet window: nothing scored on any source, so the feed pads to three newest clips and says so
// rather than filling the page with them.
export const HomeHighlightFeedOnlyNewest: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/highlight_feed/': {
                    results: [0, 1, 2].map((i) => ({
                        observation: observation({ id: `00000000-0000-0000-0000-0000000000f${i}` }),
                        reason: { kind: 'unviewed_recent' },
                    })),
                },
            },
        }),
    ],
}

export const HomeHighlightFeedEmpty: StoryObj = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/vision/scanners/highlight_feed/': { results: [] } },
        }),
    ],
}

// Billing hasn't clamped this org's limit yet, so the API still reports it as uncapped.
export const StartupProgramCap: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision()}?tab=scanners` },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tags/': { results: ['checkout', 'core flows'], next: null, count: 2 },
                '/api/projects/:team_id/vision/scanners/': scanners,
                '/api/projects/:team_id/vision/scanners/stats/': scannerStats,
                '/api/projects/:team_id/vision/quota/': { ...quota, credit_limit: null, remaining: null },
                '/api/billing/': { ...billingJson, startup_program_label: StartupProgramLabel.YC },
            },
        }),
    ],
}

// The list shows a free-only scanner that ran out as stopped, with the free-credits reason on hover.
export const ScannersListFreeCreditsUsed: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision()}?tab=scanners` },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/': {
                    ...scanners,
                    results: scanners.results.map((scanner) =>
                        scanner.id === summarizerScanner.id
                            ? { ...freeOnlyLimitReachedScanner, id: scanner.id }
                            : scanner
                    ),
                },
                '/api/projects/:team_id/vision/quota/': freeCreditsUsedQuota,
            },
        }),
    ],
}
