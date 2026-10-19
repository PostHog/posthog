import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { ConversionGoalPreviewApi, ConversionGoalPreviewResponseApi } from '../generated/api.schemas'
import { ConversionGoalDraftCard } from './ConversionGoalDraftCard'

const draft: ConversionGoalPreviewApi = {
    goal: {
        kind: 'EventsNode',
        event: 'order_settled',
        conversion_goal_id: '__preview__',
        conversion_goal_name: 'Settled orders',
        schema_map: {},
        math: 'sum',
        math_property: 'order_value',
        math_property_revenue_currency: { static: 'EUR' },
        counts_as_revenue: true,
    },
    date_from: '2026-01-01T00:00:00Z',
    date_to: '2026-01-14T23:59:59Z',
    filter_test_accounts: true,
}
const preview: ConversionGoalPreviewResponseApi = {
    preview_ref: '01800000-0000-4000-8000-000000000001',
    expires_at: '2099-01-15T00:15:00Z',
    goal: draft.goal,
    observed_at: '2026-01-15T00:00:00Z',
    date_from: draft.date_from,
    date_to: draft.date_to,
    timezone: 'UTC',
    attribution_window_days: 30,
    allows_multiple_conversions_per_visitor: true,
    filter_test_accounts: true,
    exclude_direct_traffic: false,
    exclude_unattributed: false,
    total_conversions: 4,
    evaluated_conversions: 4,
    attributed_conversions: 3,
    unattributed_conversions: 1,
    total_value: 80,
    evaluated_value: 80,
    attributed_value: 60,
    unattributed_value: 20,
    currency: 'EUR',
    conversion_limit_reached: false,
    touchpoint_limit_reached: false,
    is_approximate: false,
    warnings: [
        'Event and action sums do not deduplicate payments by transaction ID. Verify that each matching event represents a separate transaction.',
    ],
    checks_not_performed: ['transaction_uniqueness', 'business_definition_validation'],
}

const meta: Meta<typeof ConversionGoalDraftCard> = {
    title: 'Scenes-App/Marketing Analytics/Conversion goal draft',
    component: ConversionGoalDraftCard,
    parameters: { layout: 'padded' },
    decorators: [
        mswDecorator({ get: { '/api/event_definitions/': { results: [] }, '/api/projects/:team_id/actions/': [] } }),
    ],
    args: {
        draft,
        preview,
        busy: null,
        error: null,
        confirmed: false,
        saveStatus: 'idle',
        saveDisabledReason: 'Confirm the business definition and source checks first.',
        onChange: () => {},
        onConfirm: () => {},
        onPreview: () => {},
        onSave: () => {},
        onVerify: () => {},
    },
}
export default meta
type Story = StoryObj<typeof ConversionGoalDraftCard>

export const PreviewComplete: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
export const Edited: Story = { args: { preview: null, saveDisabledReason: 'Preview the current draft first.' } }
export const Approximate: Story = {
    args: { preview: { ...preview, is_approximate: true, conversion_limit_reached: true } },
}
export const SaveUncertain: Story = {
    args: { saveStatus: 'unknown', error: 'The save could not be confirmed. Check saved goals before retrying.' },
}
export const ReadOnly: Story = { args: { restrictionReason: 'You need project admin access to save a goal.' } }
export const Saved: Story = { args: { saveStatus: 'saved', confirmed: true } }
