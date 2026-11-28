import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import {
    FAILED_RUN,
    FAILED_RUN_DETAIL,
    PASSED_WITH_CHANGE_RUN,
    PASSED_WITH_CHANGE_RUN_DETAIL,
    RUNNING_RUN,
    RUNNING_RUN_DETAIL,
    RUNS_PAGE,
    RUN_JOURNEY_ID,
    RUN_JOURNEY_STEPS,
} from '../../__mocks__/journeyRuns'
import type { JourneyApi, JourneyFunnelQueryApi } from '../../generated/api.schemas'

const SIGNUP_JOURNEY: JourneyApi = {
    id: RUN_JOURNEY_ID,
    team_id: 997,
    name: 'Sign up from pricing',
    description: 'Visitors who compare plans and start a trial.',
    steps: RUN_JOURNEY_STEPS,
    conversion_window_minutes: 30,
    source: 'toolbar',
    created_by_id: 1,
    created_at: '2026-11-12T09:30:00Z',
    updated_at: '2026-11-18T14:05:00Z',
    start_url: null,
    latest_run: {
        id: FAILED_RUN.id,
        status: 'failed',
        created_at: FAILED_RUN.created_at,
        finished_at: FAILED_RUN.finished_at,
        failed_step_index: 1,
    },
}

// The first step only contains a URL, so a run has no page to open.
const UNRUNNABLE_JOURNEY: JourneyApi = {
    ...SIGNUP_JOURNEY,
    id: '0193f1a2-0000-7000-8000-000000000009',
    name: 'Upgrade from settings',
    description: '',
    steps: [{ type: 'pageview', url: '/settings/billing', url_matching: 'contains' }, RUN_JOURNEY_STEPS[3]],
    latest_run: null,
}

const JOURNEYS: JourneyApi[] = [
    SIGNUP_JOURNEY,
    {
        id: '0193f1a2-0000-7000-8000-000000000002',
        team_id: 997,
        name: 'Checkout',
        description: '',
        steps: [
            { type: 'pageview', url: '^https://shop\\.example\\.com/cart', url_matching: 'regex' },
            {
                type: 'element_click',
                selector: '#checkout',
                text: null,
                href: '/checkout',
                url: null,
                url_matching: 'exact',
            },
            { type: 'pageview', url: '/order-confirmed', url_matching: 'contains' },
        ],
        conversion_window_minutes: 60,
        source: 'manual',
        created_by_id: 1,
        created_at: '2026-10-02T11:00:00Z',
        updated_at: '2026-10-02T11:00:00Z',
        start_url: 'https://shop.example.com/cart',
        latest_run: {
            id: PASSED_WITH_CHANGE_RUN.id,
            status: 'passed',
            created_at: PASSED_WITH_CHANGE_RUN.created_at,
            finished_at: PASSED_WITH_CHANGE_RUN.finished_at,
            failed_step_index: null,
        },
    },
    {
        id: '0193f1a2-0000-7000-8000-000000000003',
        team_id: 997,
        name: 'Invite a teammate from the settings page after creating the first project',
        description: 'Members who invite a colleague after they set up their first project.',
        steps: [
            { type: 'pageview', url: '/settings/members', url_matching: 'contains' },
            {
                type: 'element_click',
                selector: '[data-attr="invite-teammate"]',
                text: 'Invite',
                href: null,
                url: null,
                url_matching: 'exact',
            },
        ],
        conversion_window_minutes: 15,
        source: 'manual',
        created_by_id: 1,
        created_at: '2026-09-21T16:45:00Z',
        updated_at: '2026-11-01T08:20:00Z',
        start_url: null,
        latest_run: null,
    },
]

const SIGNUP_FUNNEL_QUERY: JourneyFunnelQueryApi = {
    query: {
        kind: 'FunnelsQuery',
        series: [
            {
                kind: 'EventsNode',
                custom_name: 'Pageview of https://example.com/pricing',
                event: '$pageview',
                properties: [
                    { key: '$current_url', type: 'event', operator: 'exact', value: 'https://example.com/pricing' },
                ],
            },
            {
                kind: 'EventsNode',
                custom_name: 'Click on "Sign up"',
                event: '$autocapture',
                properties: [
                    { key: 'selector', type: 'element', operator: 'exact', value: 'header a.signup' },
                    { key: 'text', type: 'element', operator: 'exact', value: 'Sign up' },
                ],
            },
            {
                kind: 'EventsNode',
                custom_name: 'Pageview of /signup',
                event: '$pageview',
                properties: [{ key: '$current_url', type: 'event', operator: 'icontains', value: '/signup' }],
            },
            {
                kind: 'EventsNode',
                custom_name: 'Click on "Create account"',
                event: '$autocapture',
                properties: [
                    {
                        key: 'selector',
                        type: 'element',
                        operator: 'exact',
                        value: 'form#signup button[type="submit"]',
                    },
                ],
            },
        ],
        funnelsFilter: {
            funnelAggregateByHogQL: 'properties.$session_id',
            funnelOrderType: 'ordered',
            funnelWindowInterval: 30,
            funnelWindowIntervalUnit: 'minute',
        },
    },
} as unknown as JourneyFunnelQueryApi

function funnelStep(
    event: string,
    customName: string,
    order: number,
    count: number,
    previousCount: number
): Record<string, unknown> {
    return {
        action_id: event,
        name: event,
        custom_name: customName,
        order,
        count,
        type: 'events',
        average_conversion_time: order > 0 ? 95 : null,
        median_conversion_time: order > 0 ? 70 : null,
        converted_people_url: '/api/person/funnel/?',
        dropped_people_url: order > 0 ? '/api/person/funnel/?' : null,
        droppedOffFromPrevious: previousCount - count,
        conversionRates: {
            fromPrevious: previousCount ? count / previousCount : 1,
            total: count / 4210,
            fromBasisStep: count / 4210,
        },
    }
}

const SIGNUP_FUNNEL_RESULT = {
    result: [
        funnelStep('$pageview', 'Pageview of https://example.com/pricing', 0, 4210, 4210),
        funnelStep('$autocapture', 'Click on "Sign up"', 1, 1630, 4210),
        funnelStep('$pageview', 'Pageview of /signup', 2, 1388, 1630),
        funnelStep('$autocapture', 'Click on "Create account"', 3, 902, 1388),
    ],
    is_cached: true,
    last_refresh: '2026-11-20T00:00:00Z',
}

const PREFILL_STEPS = [
    { type: 'pageview', url: 'https://example.com/pricing', url_matching: 'exact' },
    { type: 'element_click', selector: 'button.start-trial', text: 'Start free trial' },
    { type: 'element_click', selector: '' },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/User journeys',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-11-20',
        featureFlags: [FEATURE_FLAGS.USER_JOURNEYS],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/user_journeys/': { count: JOURNEYS.length, results: JOURNEYS },
                [`/api/projects/:team_id/user_journeys/${SIGNUP_JOURNEY.id}/`]: SIGNUP_JOURNEY,
                [`/api/projects/:team_id/user_journeys/${SIGNUP_JOURNEY.id}/funnel_query/`]: SIGNUP_FUNNEL_QUERY,
                [`/api/projects/:team_id/user_journeys/${UNRUNNABLE_JOURNEY.id}/`]: UNRUNNABLE_JOURNEY,
                [`/api/projects/:team_id/user_journeys/${UNRUNNABLE_JOURNEY.id}/funnel_query/`]: SIGNUP_FUNNEL_QUERY,
                '/api/projects/:team_id/user_journeys/:journey_id/runs/': RUNS_PAGE,
                [`/api/projects/:team_id/user_journeys/:journey_id/runs/${FAILED_RUN.id}/`]: FAILED_RUN_DETAIL,
                [`/api/projects/:team_id/user_journeys/:journey_id/runs/${PASSED_WITH_CHANGE_RUN.id}/`]:
                    PASSED_WITH_CHANGE_RUN_DETAIL,
                [`/api/projects/:team_id/user_journeys/:journey_id/runs/${RUNNING_RUN.id}/`]: RUNNING_RUN_DETAIL,
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder/': { id: 'example-home', path: 'Users/Example' },
                '/api/environments/:team_id/query/:kind/': SIGNUP_FUNNEL_RESULT,
                '/api/projects/:team_id/query/:kind/': SIGNUP_FUNNEL_RESULT,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const JourneyList: Story = {
    parameters: {
        pageUrl: urls.userJourneys(),
        testOptions: { waitForSelector: '[data-attr="user-journeys-table"] tbody tr', snapshotBrowsers: [] },
    },
}

export const EmptyJourneyList: Story = {
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/user_journeys/': { count: 0, results: [] } } })],
    parameters: {
        pageUrl: urls.userJourneys(),
        testOptions: { waitForSelector: '[data-attr="product-introduction-journey"]', snapshotBrowsers: [] },
    },
}

export const NewJourneyFromToolbar: Story = {
    parameters: {
        pageUrl: urls.userJourneyNew({
            name: 'Start a trial from pricing',
            source: 'toolbar',
            steps: PREFILL_STEPS as unknown as JourneyApi['steps'],
        }),
        testOptions: { waitForSelector: '[data-attr="user-journey-step-editor"]', snapshotBrowsers: [] },
    },
}

export const JourneyDetail: Story = {
    parameters: {
        pageUrl: urls.userJourney(SIGNUP_JOURNEY.id),
        testOptions: { waitForSelector: '[data-attr="user-journey-runs-table"] tbody tr', snapshotBrowsers: [] },
    },
}

export const JourneyDetailNeverRun: Story = {
    decorators: [
        mswDecorator({ get: { '/api/projects/:team_id/user_journeys/:journey_id/runs/': { count: 0, results: [] } } }),
    ],
    parameters: {
        pageUrl: urls.userJourney(SIGNUP_JOURNEY.id),
        testOptions: { waitForSelector: '[data-attr="user-journey-runs-empty"]', snapshotBrowsers: [] },
    },
}

export const JourneyDetailWithoutStartPage: Story = {
    decorators: [
        mswDecorator({ get: { '/api/projects/:team_id/user_journeys/:journey_id/runs/': { count: 0, results: [] } } }),
    ],
    parameters: {
        pageUrl: urls.userJourney(UNRUNNABLE_JOURNEY.id),
        testOptions: { waitForSelector: '[data-attr="user-journey-runs-edit"]', snapshotBrowsers: [] },
    },
}

export const JourneyRunFailed: Story = {
    parameters: {
        pageUrl: urls.userJourneyRun(SIGNUP_JOURNEY.id, FAILED_RUN.id),
        testOptions: { waitForSelector: '[data-attr="user-journey-run-steps"] img', snapshotBrowsers: [] },
    },
}

export const JourneyRunPassedWithVisualChange: Story = {
    parameters: {
        pageUrl: urls.userJourneyRun(SIGNUP_JOURNEY.id, PASSED_WITH_CHANGE_RUN.id),
        testOptions: { waitForSelector: '[data-attr="user-journey-run-steps"] img', snapshotBrowsers: [] },
    },
}

export const JourneyRunInProgress: Story = {
    parameters: {
        pageUrl: urls.userJourneyRun(SIGNUP_JOURNEY.id, RUNNING_RUN.id),
        testOptions: { waitForSelector: '[data-attr="user-journey-run-header"]', snapshotBrowsers: [] },
    },
}
