import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { ConversionRecommendationApi, ConversionRecommendationStateApi } from '../generated/api.schemas'
import { ConversionGoalRecommendations } from './ConversionGoalRecommendations'
import { DashboardConversionRecommendations } from './DashboardConversionRecommendations'

const run = {
    id: 'synthetic-analysis',
    status: 'completed' as const,
    lookback_days: 30,
    date_from: '2026-09-01T00:00:00Z',
    date_to: '2026-10-01T00:00:00Z',
    created_at: '2026-10-01T00:00:00Z',
    completed_at: '2026-10-01T00:01:00Z',
    error: '',
}
const recommendation: ConversionRecommendationApi = {
    source_ref: 'event:order_settled',
    name: 'Settled orders',
    intent: 'revenue',
    amount_property: 'order_value',
    reason: 'This event may record completed payments. Confirm its business meaning before using it as revenue.',
    questions: ['Confirm payment status, amount units, currency, refunds, and one event per transaction.'],
    candidate: {
        source_ref: 'event:order_settled',
        name: 'order_settled',
        kind: 'EventsNode',
        event: 'order_settled',
        count: 42,
        numeric_properties: ['order_value'],
    },
}
const completed: ConversionRecommendationStateApi = {
    latest_run: run,
    result_run: run,
    can_generate: true,
    generation_disabled_reason: null,
    results: {
        recommendations: [
            recommendation,
            {
                ...recommendation,
                source_ref: 'event:quote_requested',
                name: 'Quote requests',
                intent: 'conversion',
                amount_property: null,
                reason: 'A quote request may indicate purchase intent.',
                questions: ['Does this event exclude duplicate requests?'],
                candidate: {
                    source_ref: 'event:quote_requested',
                    name: 'quote_requested',
                    kind: 'EventsNode',
                    event: 'quote_requested',
                    count: 18,
                },
            },
            {
                ...recommendation,
                source_ref: 'action:2',
                name: 'Activated accounts',
                intent: 'customer',
                amount_property: null,
                reason: 'This action may identify newly activated accounts.',
                questions: ['Does this action fire once for each new customer?'],
                candidate: { source_ref: 'action:2', name: 'Activated accounts', kind: 'ActionsNode', action_id: 2 },
            },
        ],
        limitations: [
            'Discovery considers up to 20 custom events and 20 existing actions. Business definitions need your review.',
        ],
    },
}
function withState(state: ConversionRecommendationStateApi): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/marketing_analytics/conversion_recommendations/': state,
        },
        post: {
            '/api/projects/:team_id/marketing_analytics/conversion_recommendations/start/': {
                ...state,
                latest_run: { ...run, status: 'pending', lookback_days: state.result_run ? 14 : 30 },
            },
        },
    })
}
const meta: Meta<typeof ConversionGoalRecommendations> = {
    title: 'Scenes-App/Marketing Analytics/Persisted conversion recommendations',
    component: ConversionGoalRecommendations,
    args: { onConfigureGoals: () => {}, onUseSuggestion: () => {} },
    parameters: {
        layout: 'padded',
        featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI, FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP],
    },
    decorators: [
        (Story, { parameters }) => (
            <div className={parameters.narrow ? 'w-[520px] max-w-full' : 'w-240 max-w-full'}>
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof ConversionGoalRecommendations>

export const FirstAnalysis: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        withState({
            ...completed,
            latest_run: { ...run, status: 'pending' },
            result_run: null,
            results: { recommendations: [] },
        }),
    ],
}
export const Ready: Story = { decorators: [withState(completed)] }
export const Dashboard: Story = {
    render: () => <DashboardConversionRecommendations />,
    decorators: [withState(completed)],
}
export const Updating: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    decorators: [withState({ ...completed, latest_run: { ...run, status: 'running', lookback_days: 14 } })],
}
export const Empty: Story = { decorators: [withState({ ...completed, results: { recommendations: [] } })] }
export const Failed: Story = {
    decorators: [
        withState({
            ...completed,
            latest_run: {
                ...run,
                status: 'failed',
                error: 'Could not analyze the sources. Scan again to retry.',
            },
        }),
    ],
}
export const Narrow: Story = {
    parameters: { narrow: true },
    decorators: [withState(completed)],
}

export const ConsentRequired: Story = {
    decorators: [
        withState({
            ...completed,
            latest_run: null,
            result_run: null,
            results: { recommendations: [] },
            can_generate: false,
            generation_disabled_reason: 'Ask an organization admin to enable AI data processing.',
        }),
    ],
}
