import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { recordings } from 'scenes/session-recordings/__mocks__/recordings'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { mswDecorator } from '~/mocks/browser'

import { highlightPicksLogic } from '../highlightPicksLogic'
import { HighlightPicksListColumn } from './HighlightPicksListColumn'

const playlistLogicProps = { logicKey: 'scratch-picks', autoPlay: false, updateSearchParams: false }

const manyRecordings = Array.from({ length: 14 }, (_, i) => ({
    ...recordings[i % recordings.length],
    id: `scratch-${i}`,
    recording_duration: [240, 610, 95, 1320, 480, 760, 180][i % 7],
    start_time: '2026-10-28T09:00:00Z',
    end_time: '2026-10-28T09:20:00Z',
    ongoing: false,
}))

const quota = {
    credit_limit: 10000,
    credits_used: 0,
    remaining: 10000,
    exhausted: false,
    projected_monthly_credits: 0,
    scanners_monthly_credits: 0,
    backfills_committed_credits: 0,
    free_monthly_credits: 2500,
    credits_settled: 0,
    credits_reserved: 0,
    period_start: '2026-10-01T00:00:00Z',
    period_end: '2026-11-01T00:00:00Z',
}

const estimate = {
    matched_sessions_in_window: 1380,
    window_days: 7,
    estimated_observations_per_month: 300,
    credits_per_observation: 1,
    estimated_credits_per_month: 300,
    other_enabled_scanners_monthly_credits: 0,
    free_only_monthly_credits_left: 2500,
    sampling_rate: 1,
}

const emptyScannerStats = {
    total: 0,
    enabled: 0,
    by_type: {
        monitor: { enabled: 0, total: 0 },
        classifier: { enabled: 0, total: 0 },
        scorer: { enabled: 0, total: 0 },
        summarizer: { enabled: 0, total: 0 },
        experiment: { enabled: 0, total: 0 },
    },
}

const summarizer = {
    id: '00000000-0000-0000-0000-00000000000c',
    name: 'Session highlights',
    description: '',
    tags: [],
    scanner_type: 'summarizer',
    scanner_config: { prompt: 'Summarize this session.', length: 'medium' },
    prompt_question: 'What happened in this session?',
    query: null,
    sampling_rate: 1,
    sampling_mode: 'comprehensive',
    provider: 'google',
    model: 'gemini-3.8-flash',
    enabled: true,
    emits_signals: false,
    scanner_version: 1,
    last_swept_at: '2026-10-29T00:00:00Z',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    created_by: null,
    credits_this_month: 212,
    observations_this_month: 212,
    credits_per_observation: 1,
    estimated_monthly_observations: 300,
    estimated_monthly_credits: 300,
    estimated_at: '2026-10-10T00:00:00Z',
    user_access_level: 'editor',
    sweep_throttle_factor: 1,
    dashboard_id: null,
    dashboard_suggested: false,
    limit_reached: false,
}

const pick = (id: string, title: string, summary: string, createdAt: string): any => ({
    observation: {
        id,
        scanner_id: summarizer.id,
        session_id: `0199${id.slice(-4)}-70a1-7c52-a4d5-3f9b2e8c1d07`,
        status: 'succeeded',
        error_reason: '',
        workflow_id: `vision-observation-${id}`,
        scanner_origin: 'configured',
        scanner_snapshot: {
            name: summarizer.name,
            scanner_type: 'summarizer',
            scanner_version: 1,
            model: 'gemini-3.8-flash',
            provider: 'google',
            emits_signals: false,
            scanner_config: summarizer.scanner_config,
        },
        scanner_result: {
            model_output: { scanner_type: 'summarizer', confidence: 0.8, title, summary },
            signals_count: 0,
        },
        prompt_question: null,
        prompt_valence: null,
        triggered_by: 'schedule',
        triggered_by_user: null,
        distinct_id: 'user_8f3k2j',
        recording_subject_email: 'alice@example.com',
        previous_observation_id: null,
        next_observation_id: null,
        label: null,
        viewed: true,
        started_at: createdAt,
        completed_at: createdAt,
        created_at: createdAt,
        media: [],
    },
    reason: { kind: 'unviewed_recent' },
})

const quietWeekPicks = [
    pick(
        '00000000-0000-0000-0000-0000000000a1',
        'Checkout hesitation after coupon',
        'The user applied a coupon, hit a validation error twice, and left.',
        '2026-10-26T09:00:00Z'
    ),
    pick(
        '00000000-0000-0000-0000-0000000000a2',
        'Plan limit blocked an export',
        'The export stopped at the plan limit and the user opened billing.',
        '2026-10-25T15:00:00Z'
    ),
    pick(
        '00000000-0000-0000-0000-0000000000a3',
        'Browsed pricing and left',
        'The user compared two plans and left without signing up.',
        '2026-10-25T11:00:00Z'
    ),
]

function PicksColumn(): JSX.Element {
    const { setListMode } = useActions(highlightPicksLogic)
    useEffect(() => {
        setListMode('picks')
    }, [setListMode])
    return (
        <div className="flex w-[380px] flex-col rounded border bg-bg-light">
            <HighlightPicksListColumn recordingsList={<div />} />
        </div>
    )
}

const meta: Meta = {
    title: 'Scratch/HighlightPicksStates',
    decorators: [
        (Story) => (
            <BindLogic logic={sessionRecordingsPlaylistLogic} props={playlistLogicProps}>
                <BindLogic logic={highlightPicksLogic} props={{ logicKey: 'scratch-picks', playlistLogicProps }}>
                    <Story />
                </BindLogic>
            </BindLogic>
        ),
        mswDecorator({
            get: {
                '/api/environments/:team_id/session_recordings/': { results: manyRecordings, has_next: false },
                '/api/projects/:team_id/vision/quota/': quota,
                '/api/projects/:team_id/vision/scanners/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/vision/scanners/stats/': emptyScannerStats,
                '/api/projects/:team_id/vision/scanners/creators/': { creators: [] },
                '/api/projects/:team_id/vision/scanners/highlight_feed/': { has_more: false, results: [] },
                '/api/projects/:team_id/vision/scanners/:id/observations/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                '/api/projects/:team_id/vision/scanners/:id/observations/stats/': {
                    status_counts: {
                        total: 212,
                        succeeded: 208,
                        failed: 4,
                        ineligible: 0,
                        in_flight: 0,
                        success_rate: 0.98,
                    },
                    labels: {
                        up_total: 0,
                        down_total: 0,
                        by_day: [],
                        by_rating_day: [],
                        version_markers: [{ version: 1, first_observation_at: '2026-10-01T00:00:00Z' }],
                    },
                },
            },
            post: {
                '/api/projects/:team_id/vision/scanners/estimate/': estimate,
                '/api/projects/:team_id/vision/scanners/:id/backfills/estimate/': {
                    total_sessions: 212,
                    total_credits: 212,
                },
            },
        }),
    ],
    render: () => <PicksColumn />,
}
export default meta

type Story = StoryObj

export const StarterWithVolume: Story = {}

export const StarterLoading: Story = {
    decorators: [
        mswDecorator({
            post: { '/api/projects/:team_id/vision/scanners/estimate/': () => new Promise(() => {}) },
        }),
    ],
}

export const StarterNoRecordings: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/environments/:team_id/session_recordings/': { results: [], has_next: false } },
            post: {
                '/api/projects/:team_id/vision/scanners/estimate/': { ...estimate, matched_sessions_in_window: 0 },
            },
        }),
    ],
}

export const StarterFreeCreditsUsed: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/quota/': {
                    ...quota,
                    credits_used: 2500,
                    credits_settled: 2500,
                    remaining: 7500,
                },
            },
            post: {
                '/api/projects/:team_id/vision/scanners/estimate/': { ...estimate, free_only_monthly_credits_left: 0 },
            },
        }),
    ],
}

export const QuietWeek: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [summarizer],
                },
                '/api/projects/:team_id/vision/scanners/stats/': {
                    ...emptyScannerStats,
                    total: 1,
                    enabled: 1,
                    by_type: { ...emptyScannerStats.by_type, summarizer: { enabled: 1, total: 1 } },
                },
                '/api/projects/:team_id/vision/scanners/highlight_feed/': { has_more: false, results: quietWeekPicks },
            },
        }),
    ],
}
