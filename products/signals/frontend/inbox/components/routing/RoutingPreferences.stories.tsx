import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { SignalProductDomainApi } from 'products/signals/frontend/generated/api.schemas'

import { RoutingPreferences } from './RoutingPreferences'

const domain: SignalProductDomainApi = {
    id: '11111111-1111-4111-8111-111111111111',
    name: 'Checkout',
    description: 'Purchases and payment confirmation. Delivery tracking belongs to Delivery.',
    owning_role_id: '22222222-2222-4222-8222-222222222222',
    owning_role_name: 'Commerce',
    repository: 'example/store',
    code_paths: ['src/checkout/'],
    archived: false,
    revision: 1,
    import_state: {},
}
const page = <T,>(results: T[]): { count: number; results: T[]; next: null; previous: null } => ({
    count: results.length,
    results,
    next: null,
    previous: null,
})
const mocks = mswDecorator({
    get: {
        '/api/projects/:projectId/signals/domains/': page([domain]),
        '/api/projects/:projectId/signals/domains/teams/': [
            { id: domain.owning_role_id, name: 'Commerce', is_member: false },
        ],
        '/api/projects/:projectId/signals/routing_preferences/': page([
            {
                id: '33333333-3333-4333-8333-333333333333',
                domain,
                excluded: true,
                revision: 1,
                updated_at: '2026-01-01T12:00:00Z',
            },
        ]),
        '/api/projects/:projectId/signals/routing_batches/': page([]),
        '/api/projects/:projectId/signals/routing_preferences/suggestions/': [],
    },
})

const meta: Meta<typeof RoutingPreferences> = {
    title: 'Scenes-App/Inbox/RoutingPreferences',
    component: RoutingPreferences,
    decorators: [mocks],
    parameters: { layout: 'padded', testOptions: { waitForSelector: '[data-attr="inbox-routing-disable-rule"]' } },
}
export default meta
type Story = StoryObj<typeof RoutingPreferences>

export const ExcludedDomain: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-80">
                <Story />
            </div>
        ),
    ],
}
