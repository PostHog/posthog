import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/react'

import { mswDecorator } from '~/mocks/browser'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import type { ErrorTrackingTagRule } from '../rules/types'
import { TagRules } from './TagRules'

const RULES: ErrorTrackingTagRule[] = [
    {
        id: '0193a3f0-0000-7000-8000-000000000001',
        key: 'rule_0193a3f000007000800000000001',
        label: 'Checkout',
        description: 'Errors raised on the checkout pages.',
        filters: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: '$current_url',
                    value: '/checkout',
                    operator: PropertyOperator.IContains,
                    type: PropertyFilterType.Event,
                },
            ],
        },
        order_key: 0,
        disabled_data: null,
        created_at: '2026-11-02T10:00:00Z',
        updated_at: '2026-11-02T10:00:00Z',
    },
    {
        id: '0193a3f0-0000-7000-8000-000000000002',
        key: 'rule_0193a3f000007000800000000002',
        label: 'Unhandled errors in old Safari and Firefox versions that customers still report',
        description: '',
        filters: {
            type: FilterLogicalOperator.Or,
            values: [
                {
                    key: '$browser',
                    value: ['Safari', 'Firefox'],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
                {
                    key: '$exception_handled',
                    value: ['false'],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
        },
        order_key: 1,
        disabled_data: null,
        created_at: '2026-11-03T10:00:00Z',
        updated_at: '2026-11-09T10:00:00Z',
    },
    {
        id: '0193a3f0-0000-7000-8000-000000000003',
        key: 'rule_0193a3f000007000800000000003',
        label: 'Large orders',
        description: 'Errors on orders above 1,000.',
        filters: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: 'order_total',
                    value: 1000,
                    operator: PropertyOperator.GreaterThan,
                    type: PropertyFilterType.Event,
                },
            ],
        },
        order_key: 2,
        disabled_data: { message: 'The rule exceeds the maximum bytecode size.' },
        created_at: '2026-11-04T10:00:00Z',
        updated_at: '2026-11-04T10:00:00Z',
    },
]

const meta: Meta<typeof TagRules> = {
    title: 'Scenes-App/ErrorTracking/Settings/TagRules',
    component: TagRules,
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/error_tracking/tag_rules/': { results: RULES } },
        }),
    ],
    // A narrow container matches a settings scene with the side panel open.
    render: () => (
        <div className="w-[520px]">
            <TagRules />
        </div>
    ),
    parameters: {
        layout: 'padded',
        mockDate: '2026-11-16',
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=Large orders' },
    },
}
export default meta

type Story = StoryObj<typeof TagRules>

export const List: Story = {}

export const EditDisabledRule: Story = {
    play: async ({ canvasElement }) => {
        fireEvent.click(await within(canvasElement).findByText('Large orders'))
        await within(document.body).findByText('Edit label rule')
        await within(document.body).findByText(/maximum bytecode size/)
    },
}
