import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type {
    IdentityMatchingLinkApi,
    IdentityMatchingPersonApi,
    IdentityMatchingRunApi,
} from './generated/api.schemas'

const RUN_A = '0197a4a6-06d9-7000-34fe-daa2e2afb501'
const RUN_B = '0197a4a6-06d9-7000-34fe-daa2e2afb502'

function person(distinct_id: string, overrides: Partial<IdentityMatchingPersonApi>): IdentityMatchingPersonApi {
    return {
        distinct_id,
        first_seen: '2023-01-15T10:20:00Z',
        last_seen: '2023-02-01T09:25:00Z',
        email: null,
        name: null,
        city: null,
        country: null,
        browser: null,
        os: null,
        device_type: null,
        timezone: null,
        utm_source: null,
        utm_medium: null,
        utm_campaign: null,
        referring_domain: null,
        gclid: null,
        ...overrides,
    }
}

const BASE_LINKS: Omit<IdentityMatchingLinkApi, 'orphan_person' | 'anchor_person'>[] = [
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

// Resolved persons keyed by distinct ID. Links to the same identity (e.g. the rules + logreg links
// for Anna) share these. A null entry exercises the "no profile resolved" fallback.
const PERSON_BY_DISTINCT_ID: Record<string, IdentityMatchingPersonApi | null> = {
    '0190a1b2-phone-3c4d-5e6f-anna00000001': person('0190a1b2-phone-3c4d-5e6f-anna00000001', {
        city: 'Lisbon',
        country: 'PT',
        browser: 'Mobile Safari',
        os: 'iOS',
        device_type: 'Mobile',
        timezone: 'Europe/Lisbon',
        utm_source: 'google',
        utm_medium: 'cpc',
        utm_campaign: 'spring_sale_2026',
        referring_domain: 'google.com',
        gclid: 'Cj0KCQiAexampleLISBON',
    }),
    'anna@example.com': person('anna@example.com', {
        email: 'anna@example.com',
        name: 'Anna Müller',
        city: 'Lisbon',
        country: 'PT',
        browser: 'Chrome',
        os: 'macOS',
        device_type: 'Desktop',
        timezone: 'Europe/Lisbon',
    }),
    '0190a1b2-webview-3c4d-5e6f-cara00000001': person('0190a1b2-webview-3c4d-5e6f-cara00000001', {
        city: 'Berlin',
        country: 'DE',
        browser: 'Chrome WebView',
        os: 'Android',
        device_type: 'Mobile',
        timezone: 'Europe/Berlin',
        utm_source: 'linkedin',
        utm_medium: 'paid',
        utm_campaign: 'q2_webinar',
        referring_domain: 'lnkd.in',
    }),
    'cara@example.com': person('cara@example.com', {
        email: 'cara@example.com',
        name: 'Cara Lopes',
        city: 'Berlin',
        country: 'DE',
        browser: 'Chrome WebView',
        os: 'Android',
        device_type: 'Mobile',
        timezone: 'Europe/Berlin',
        utm_source: 'linkedin',
        utm_medium: 'paid',
        utm_campaign: 'q2_webinar',
        referring_domain: 'lnkd.in',
    }),
    '0190a1b2-phone-3c4d-5e6f-bob000000001': person('0190a1b2-phone-3c4d-5e6f-bob000000001', {
        city: 'New York',
        country: 'US',
        browser: 'Mobile Safari',
        os: 'iOS',
        device_type: 'Mobile',
        timezone: 'America/New_York',
    }),
    'bob@example.com': person('bob@example.com', {
        email: 'bob@example.com',
        city: 'New York',
        country: 'US',
        browser: 'Chrome',
        os: 'Windows',
        device_type: 'Desktop',
        timezone: 'America/New_York',
    }),
    '0190a1b2-tablet-3c4d-5e6f-dana00000001': person('0190a1b2-tablet-3c4d-5e6f-dana00000001', {
        city: 'London',
        country: 'GB',
        browser: 'Safari',
        os: 'iPadOS',
        device_type: 'Tablet',
        timezone: 'Europe/London',
    }),
    'dana@example.com': person('dana@example.com', {
        email: 'dana@example.com',
        city: 'Manchester',
        country: 'GB',
        browser: 'Chrome',
        os: 'Windows',
        device_type: 'Desktop',
        timezone: 'Europe/London',
        utm_source: 'bing',
        utm_medium: 'cpc',
        utm_campaign: 'brand',
    }),
    '0190a1b2-anon-3c4d-5e6f-eve0000000001': null,
    '0190a1b2-user-3c4d-5e6f-eve0000000002': person('0190a1b2-user-3c4d-5e6f-eve0000000002', {
        browser: 'Firefox',
        os: 'Linux',
        device_type: 'Desktop',
        timezone: 'UTC',
    }),
}

const LINKS_RESULT: IdentityMatchingLinkApi[] = BASE_LINKS.map((link) => ({
    ...link,
    orphan_person: PERSON_BY_DISTINCT_ID[link.orphan_distinct_id] ?? null,
    anchor_person: PERSON_BY_DISTINCT_ID[link.anchor_person_key] ?? null,
}))

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
