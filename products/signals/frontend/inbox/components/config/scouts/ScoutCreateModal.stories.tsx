import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { ScoutCreateModal } from './ScoutCreateModal'

// The form opened on a scout that already exists, to turn it on. The name, description and
// instructions are read-only, and only the run settings can change. ScoutNewButton stories cover
// the form that creates a new scout.

const meta: Meta<typeof ScoutCreateModal> = {
    title: 'Scenes-App/Inbox/ScoutCreateModal',
    component: ScoutCreateModal,
    parameters: {
        mockDate: '2026-06-11',
        testOptions: { snapshotTargetSelector: '.LemonModal', waitForLoadersToDisappear: false },
    },
    args: {
        isOpen: true,
        onClose: () => {},
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs/': () => [200, []],
                '/api/projects/:id/mcp_gateway/service_accounts/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ScoutCreateModal>

export const TurnOnExistingScout: Story = {
    args: {
        initialValues: {
            existingConfigId: 'scout-checkout-failures',
            display_name: 'Checkout failures',
            name: 'signals-scout-checkout-failures',
            description: 'Investigates recurring checkout failures and reports meaningful changes.',
            body: [
                '# Checkout failures',
                '',
                'Look at exceptions raised on the checkout pages in the last day.',
                'Group them by error type and compare with the week before.',
                'Report a group only when it is new or grew by more than half.',
            ].join('\n'),
            config: { run_interval_minutes: 1440, tags: ['checkout', 'errors'] },
        },
    },
}
