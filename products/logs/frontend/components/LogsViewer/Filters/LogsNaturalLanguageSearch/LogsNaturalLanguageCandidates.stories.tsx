import type { Meta, StoryObj } from '@storybook/react'

import type { _LogsNaturalLanguageCandidateApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsNaturalLanguageCandidates } from './LogsNaturalLanguageCandidates'

const meta: Meta<typeof LogsNaturalLanguageCandidates> = {
    title: 'Scenes-App/Logs/Natural language candidates',
    component: LogsNaturalLanguageCandidates,
    parameters: { layout: 'padded' },
    decorators: [
        (Story) => (
            <div className="w-[400px]">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof LogsNaturalLanguageCandidates>

const CANDIDATES: _LogsNaturalLanguageCandidateApi[] = [
    {
        label: 'Errors from checkout in the last 2 hours',
        query: {
            dateRange: { date_from: '-2h' },
            severityLevels: ['error', 'fatal'],
            serviceNames: ['checkout'],
            filterGroup: [],
        },
        probability: 0.55,
    },
    {
        label: 'Logs mentioning "checkout error" in the last 2 hours',
        query: {
            dateRange: { date_from: '-2h' },
            severityLevels: [],
            serviceNames: [],
            filterGroup: [{ key: 'message', type: 'log', operator: 'icontains', value: 'checkout error' }],
        },
        probability: 0.3,
    },
    {
        label: 'Errors with a checkout route in the last 2 hours',
        query: {
            dateRange: { date_from: '-2h' },
            severityLevels: ['error'],
            serviceNames: [],
            filterGroup: [{ key: 'http.route', type: 'log_attribute', operator: 'icontains', value: 'checkout' }],
        },
        probability: 0.15,
    },
]

export const Ranked: Story = {
    args: { candidates: CANDIDATES, onApply: () => {} },
}

export const Unranked: Story = {
    args: { candidates: CANDIDATES.map((c) => ({ ...c, probability: null })), onApply: () => {} },
}
