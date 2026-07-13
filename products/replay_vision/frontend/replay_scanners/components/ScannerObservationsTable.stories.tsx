import type { Meta, StoryObj } from '@storybook/react'
import { screen, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { ObservationStatsApi, ReplayObservationApi, ReplayScannerApi } from '../../generated/api.schemas'
import {
    ObservationStatusEnumApi,
    ObservationTriggerEnumApi,
    ScannerModelEnumApi,
    ScannerProviderEnumApi,
    ScannerTypeEnumApi,
} from '../../generated/api.schemas'
import { ScannerObservationsTable } from './ScannerObservationsTable'

const SCANNER_ID = '00000000-0000-0000-0000-00000000000b'

const TAGS = [
    'actively-read',
    'agent_scouts',
    'ai_agents_interest',
    'ai_analysis',
    'ai_assistance',
    'architecture_deep_dive',
    'sdk_docs_review',
    'technical_docs_research',
]

const scanner = {
    id: SCANNER_ID,
    name: 'Frustration tags',
    description: 'Tags sessions with the likely intent behind the recording.',
    scanner_type: ScannerTypeEnumApi.Classifier,
    scanner_config: {
        prompt: 'Tag this session.',
        tags: TAGS,
        multi_label: true,
        allow_freeform_tags: true,
    },
    query: null,
    sampling_rate: 1,
    sampling_mode: 'comprehensive',
    provider: ScannerProviderEnumApi.Google,
    model: ScannerModelEnumApi.Gemini3FlashPreview,
    enabled: true,
    emits_signals: false,
    scanner_version: 2,
    estimated_monthly_observations: 534,
    credits_per_observation: 5,
    estimated_monthly_credits: 2670,
    last_swept_at: '2026-05-12T00:00:00Z',
    created_at: '2026-05-12T00:00:00Z',
    created_by: null,
    updated_at: '2026-05-12T00:00:00Z',
    feedback_themes: null,
} satisfies ReplayScannerApi

const observation = (
    id: string,
    subject: string,
    tags: string[],
    createdAt: string
): ReplayObservationApi => ({
    id,
    scanner_id: SCANNER_ID,
    session_id: id,
    status: ObservationStatusEnumApi.Succeeded,
    error_reason: '',
    workflow_id: `workflow-${id}`,
    scanner_snapshot: {
        name: scanner.name,
        scanner_type: ScannerTypeEnumApi.Classifier,
        scanner_version: scanner.scanner_version,
        model: scanner.model,
        provider: scanner.provider,
        emits_signals: scanner.emits_signals,
        scanner_config: scanner.scanner_config,
    },
    scanner_result: {
        model_output: {
            scanner_type: ScannerTypeEnumApi.Classifier,
            tags,
            tags_freeform: tags.includes('actively-read') ? ['technical_docs_research'] : [],
            confidence: 0.93,
            reasoning: 'The session focused on reading technical docs.',
        },
        signals_count: 0,
    },
    triggered_by: ObservationTriggerEnumApi.Schedule,
    triggered_by_user: null,
    distinct_id: subject,
    recording_subject_email: subject,
    previous_observation_id: null,
    next_observation_id: null,
    label: null,
    started_at: createdAt,
    completed_at: createdAt,
    created_at: createdAt,
})

const observations = [
    observation(
        '019f59ae-df35-7bd5-845c-96fe21db473a',
        'geetaapppublications@example.com',
        ['actively-read'],
        '2026-05-12T09:00:00Z'
    ),
    observation(
        '019f592d-a91b-7212-ab89-a8cc4909459',
        'tommy@example.com',
        ['technical_docs_research'],
        '2026-05-12T08:30:00Z'
    ),
    observation(
        '019f595d-5660-7959-b16f-a584649871e2',
        'jerrelle@example.com',
        ['sdk_docs_review'],
        '2026-05-12T08:00:00Z'
    ),
]

const stats: ObservationStatsApi = {
    status_counts: {
        total: 534,
        succeeded: 518,
        failed: 8,
        ineligible: 8,
        in_flight: 0,
        success_rate: 98,
    },
    coverage: {
        recent_sessions: 534,
        total_sessions: 534,
        recent_days: 14,
    },
    labels: {
        up_total: 0,
        down_total: 0,
        by_day: [],
        by_rating_day: [],
        version_markers: [],
    },
    available_tags: TAGS,
    monitor: null,
    classifier: {
        fixed_ranked: TAGS.map((tag, index) => ({ tag, count: 18 - index })),
        freeform_ranked: [{ tag: 'technical_docs_research', count: 9 }],
        total_with_tags: 518,
    },
    scorer: null,
}

const meta = {
    title: 'Products/Replay Vision/Scanner observations table',
    component: ScannerObservationsTable,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-12',
        pageUrl: urls.replayVision(SCANNER_ID),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/vision/scanners/:id/': scanner,
                '/api/projects/:team/vision/scanners/:id/observations/': {
                    count: observations.length,
                    next: null,
                    previous: null,
                    results: observations,
                },
                '/api/projects/:team/vision/scanners/:id/observations/stats/': stats,
            },
            post: {
                '/api/projects/:team/vision/scanners/estimate/': {
                    matched_sessions_in_window: 534,
                    window_days: 30,
                    estimated_observations_per_month: 534,
                    credits_per_observation: 5,
                    estimated_credits_per_month: 2670,
                    other_enabled_scanners_monthly_credits: 0,
                    sampling_rate: 1,
                },
            },
        }),
    ],
    render: () => (
        <div className="p-6 min-w-[1180px]">
            <ScannerObservationsTable scannerId={SCANNER_ID} />
        </div>
    ),
} satisfies Meta<typeof ScannerObservationsTable>

export default meta

type Story = StoryObj<typeof meta>

export const FilterBar: Story = {
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText('Observation history')
        await within(canvasElement).findByText('actively-read')
    },
}

export const TagMenuOpen: Story = {
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText('Observation history')
        await within(canvasElement).findByText('actively-read')
        const tagFilter = canvasElement.querySelector('[data-attr="vision-observations-tag-filter"] input')
        if (!tagFilter) {
            throw new Error('Tag filter input not found')
        }
        await userEvent.click(tagFilter)
        await screen.findByRole('button', { name: 'Clear all' })
    },
}
