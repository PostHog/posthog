import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { IdentityMatchingLinkApi, IdentityMatchingRunApi } from './generated/api.schemas'

const RUN_A = '0197a4a6-06d9-7000-34fe-daa2e2afb501'
const RUN_B = '0197a4a6-06d9-7000-34fe-daa2e2afb502'

const LINKS_RESULT: IdentityMatchingLinkApi[] = [
    {
        job_id: RUN_A,
        model_version: 'rules_v1',
        orphan_distinct_id: '0190a1b2-phone-3c4d-5e6f-anna00000001',
        anchor_person_key: 'anna@example.com',
        score: 6.92,
        margin: 6.92,
        tier: 'high',
        computed_at: '2023-02-01T09:30:00Z',
        shared_ip_days: 3,
        shared_ips: 1,
        min_ip_block_size: 2,
        geo_city_match: true,
        timezone_match: true,
        language_match: true,
        ua_exact_match: false,
        orphan_is_webview: false,
        device_type_complement: true,
        days_overlap: 3,
        avg_path_jaccard: 0.33,
        orphan_paid_touch: true,
        anchor_paid_touch: false,
    },
    {
        job_id: RUN_A,
        model_version: 'rules_v1',
        orphan_distinct_id: '0190a1b2-webview-3c4d-5e6f-cara00000001',
        anchor_person_key: 'cara@example.com',
        score: 8.5,
        margin: 8.5,
        tier: 'high',
        computed_at: '2023-02-01T09:30:00Z',
        shared_ip_days: 1,
        shared_ips: 1,
        min_ip_block_size: 2,
        geo_city_match: true,
        timezone_match: true,
        language_match: true,
        ua_exact_match: true,
        orphan_is_webview: true,
        device_type_complement: false,
        days_overlap: 1,
        avg_path_jaccard: 1,
        orphan_paid_touch: true,
        anchor_paid_touch: true,
    },
    {
        job_id: RUN_A,
        model_version: 'logreg_v1',
        orphan_distinct_id: '0190a1b2-phone-3c4d-5e6f-anna00000001',
        anchor_person_key: 'anna@example.com',
        score: 0.94,
        margin: 0.94,
        tier: 'high',
        computed_at: '2023-02-01T09:30:00Z',
        shared_ip_days: 3,
        shared_ips: 1,
        min_ip_block_size: 2,
        geo_city_match: true,
        timezone_match: true,
        language_match: true,
        ua_exact_match: false,
        orphan_is_webview: false,
        device_type_complement: true,
        days_overlap: 3,
        avg_path_jaccard: 0.33,
        orphan_paid_touch: true,
        anchor_paid_touch: false,
    },
    {
        job_id: RUN_A,
        model_version: 'rules_v1',
        orphan_distinct_id: '0190a1b2-phone-3c4d-5e6f-bob000000001',
        anchor_person_key: 'bob@example.com',
        score: 4.5,
        margin: 1.75,
        tier: 'medium',
        computed_at: '2023-02-01T09:30:00Z',
        shared_ip_days: 2,
        shared_ips: 1,
        min_ip_block_size: 3,
        geo_city_match: true,
        timezone_match: true,
        language_match: false,
        ua_exact_match: false,
        orphan_is_webview: false,
        device_type_complement: true,
        days_overlap: 2,
        avg_path_jaccard: 0.1,
        orphan_paid_touch: false,
        anchor_paid_touch: false,
    },
    {
        job_id: RUN_A,
        model_version: 'rules_v1',
        orphan_distinct_id: '0190a1b2-tablet-3c4d-5e6f-dana00000001',
        anchor_person_key: 'dana@example.com',
        score: 3.05,
        margin: 0.3,
        tier: 'low',
        computed_at: '2023-02-01T09:30:00Z',
        shared_ip_days: 1,
        shared_ips: 1,
        min_ip_block_size: 8,
        geo_city_match: false,
        timezone_match: true,
        language_match: true,
        ua_exact_match: false,
        orphan_is_webview: false,
        device_type_complement: false,
        days_overlap: 1,
        avg_path_jaccard: 0,
        orphan_paid_touch: false,
        anchor_paid_touch: true,
    },
    {
        job_id: RUN_A,
        model_version: 'logreg_v1',
        orphan_distinct_id: '0190a1b2-anon-3c4d-5e6f-eve0000000001',
        anchor_person_key: '0190a1b2-user-3c4d-5e6f-eve0000000002',
        score: 0.42,
        margin: 0.15,
        tier: 'low',
        computed_at: '2023-02-01T09:30:00Z',
        shared_ip_days: 1,
        shared_ips: 2,
        min_ip_block_size: 15,
        geo_city_match: false,
        timezone_match: false,
        language_match: true,
        ua_exact_match: false,
        orphan_is_webview: false,
        device_type_complement: false,
        days_overlap: 1,
        avg_path_jaccard: 0,
        orphan_paid_touch: false,
        anchor_paid_touch: false,
    },
]

const RUNS_RESULT: IdentityMatchingRunApi[] = [
    {
        job_id: RUN_A,
        computed_at: '2023-02-01T09:30:00Z',
        first_link_at: '2023-02-01T09:28:00Z',
        last_link_at: '2023-02-01T09:31:00Z',
        total_links: 6,
        unique_orphans: 4,
        paid_touches: 2,
        models: [
            { model_version: 'rules_v1', link_count: 4, high_confidence: 2, medium_confidence: 1, low_confidence: 1 },
            { model_version: 'logreg_v1', link_count: 2, high_confidence: 1, medium_confidence: 0, low_confidence: 1 },
        ],
    },
    {
        job_id: RUN_B,
        computed_at: '2023-01-25T09:30:00Z',
        first_link_at: '2023-01-25T09:29:00Z',
        last_link_at: '2023-01-25T09:30:30Z',
        total_links: 2,
        unique_orphans: 2,
        paid_touches: 0,
        models: [
            { model_version: 'rules_v1', link_count: 2, high_confidence: 1, medium_confidence: 1, low_confidence: 0 },
        ],
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/IdentityMatching',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-02', // To stabilize relative dates
        pageUrl: urls.identityMatching(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/identity_matching_links/': {
                    results: LINKS_RESULT,
                    count: LINKS_RESULT.length,
                },
                '/api/projects/:team_id/identity_matching_links/runs/': {
                    results: RUNS_RESULT,
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const IdentityMatchingLinks: Story = {}

export const IdentityMatchingEmpty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/identity_matching_links/': { results: [], count: 0 },
                '/api/projects/:team_id/identity_matching_links/runs/': { results: [] },
            },
        }),
    ],
}

export const IdentityMatchingHighConfidenceOnly: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/identity_matching_links/': {
                    results: LINKS_RESULT.filter((l) => l.tier === 'high'),
                    count: LINKS_RESULT.filter((l) => l.tier === 'high').length,
                },
                '/api/projects/:team_id/identity_matching_links/runs/': {
                    results: RUNS_RESULT,
                },
            },
        }),
    ],
}

export const IdentityMatchingLogregOnly: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/identity_matching_links/': {
                    results: LINKS_RESULT.filter((l) => l.model_version === 'logreg_v1'),
                    count: LINKS_RESULT.filter((l) => l.model_version === 'logreg_v1').length,
                },
                '/api/projects/:team_id/identity_matching_links/runs/': {
                    results: RUNS_RESULT,
                },
            },
        }),
    ],
}

export const IdentityMatchingPaidAttribution: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/identity_matching_links/': {
                    results: LINKS_RESULT.filter((l) => l.orphan_paid_touch),
                    count: LINKS_RESULT.filter((l) => l.orphan_paid_touch).length,
                },
                '/api/projects/:team_id/identity_matching_links/runs/': {
                    results: RUNS_RESULT,
                },
            },
        }),
    ],
}
