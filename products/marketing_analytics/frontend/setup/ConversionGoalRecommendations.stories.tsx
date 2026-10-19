import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'

import type {
    ConversionGoalApi,
    ConversionGoalPreviewApi,
    ConversionGoalPreviewResponseApi,
    ConversionRecommendationApi,
    ConversionRecommendationStateApi,
} from '../generated/api.schemas'
import { ConversionGoalRecommendations } from './ConversionGoalRecommendations'

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
    state: 'needs_decision',
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
    draft: {
        goal: {
            kind: 'EventsNode',
            event: 'order_settled',
            conversion_goal_id: 'preview',
            conversion_goal_name: 'Settled orders',
            schema_map: {},
            math: 'sum',
            math_property: 'order_value',
            counts_as_revenue: true,
        },
        date_from: run.date_from,
        date_to: run.date_to,
        filter_test_accounts: true,
    },
}
const completed: ConversionRecommendationStateApi = {
    latest_run: run,
    result_run: run,
    can_generate: true,
    generation_disabled_reason: null,
    results: {
        recommendations: [recommendation],
        limitations: [
            'Discovery considers up to 20 custom events and 20 existing actions. Business definitions need your review.',
        ],
    },
}
function withState(state: ConversionRecommendationStateApi): ReturnType<typeof mswDecorator> {
    let savedGoals: ConversionGoalApi[] = []
    return mswDecorator({
        get: {
            '/api/projects/:team_id/marketing_analytics/conversion_goals/': () => ({
                goals: [],
                conversion_goals: savedGoals,
                attribution_window_days: 30,
                attribution_mode: 'last_touch',
                has_misconfigured: false,
                filter_test_accounts: true,
                base_currency: 'USD',
            }),
            '/api/projects/:team_id/marketing_analytics/conversion_recommendations/': state,
            '/api/projects/:team_id/marketing_analytics/setup_plan/': { suggestions: [] },
        },
        post: {
            '/api/projects/:team_id/marketing_analytics/conversion_goals/preview/': async ({
                request,
            }: MockResolverInfo) => {
                const draft = (await request.json()) as ConversionGoalPreviewApi
                const preview: ConversionGoalPreviewResponseApi = {
                    goal: draft.goal,
                    preview_ref: '01800000-0000-4000-8000-000000000001',
                    expires_at: '2099-01-01T00:00:00Z',
                    observed_at: run.date_to,
                    date_from: run.date_from,
                    date_to: run.date_to,
                    timezone: 'UTC',
                    attribution_window_days: 30,
                    allows_multiple_conversions_per_visitor: true,
                    filter_test_accounts: true,
                    exclude_direct_traffic: false,
                    exclude_unattributed: false,
                    total_conversions: 42,
                    evaluated_conversions: 42,
                    attributed_conversions: 30,
                    unattributed_conversions: 12,
                    total_value: 4200,
                    evaluated_value: 4200,
                    attributed_value: 3000,
                    unattributed_value: 1200,
                    currency: 'USD',
                    conversion_limit_reached: false,
                    touchpoint_limit_reached: false,
                    is_approximate: false,
                    warnings: [],
                    checks_not_performed: ['business_definition_validation'],
                }
                return preview
            },
            '/api/projects/:team_id/marketing_analytics/conversion_goals/apply/': async ({
                request,
            }: MockResolverInfo) => {
                const { goal } = (await request.json()) as { goal: ConversionGoalApi }
                const saved = { ...goal, conversion_goal_id: 'synthetic-saved-goal' }
                savedGoals = [saved]
                return { goal: saved, conversion_goals: savedGoals }
            },
            '/api/projects/:team_id/marketing_analytics/conversion_recommendations/start/': {
                ...state,
                latest_run: { ...run, status: 'pending', lookback_days: state.latest_run ? 14 : 30 },
            },
        },
    })
}
const meta: Meta<typeof ConversionGoalRecommendations> = {
    title: 'Scenes-App/Marketing Analytics/Persisted conversion recommendations',
    component: ConversionGoalRecommendations,
    parameters: {
        layout: 'padded',
        featureFlags: [
            FEATURE_FLAGS.PHAI_SANDBOX_MODE,
            FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN,
            FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI,
        ],
    },
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
                error: 'Could not analyze the sources. Update recommendations to retry, or review events with PostHog AI.',
            },
        }),
    ],
}
export const Narrow: Story = {
    decorators: [
        withState(completed),
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
