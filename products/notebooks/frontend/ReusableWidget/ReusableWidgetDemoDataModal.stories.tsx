import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { ReusableWidgetDemoDataModal } from './ReusableWidgetDemoDataModal'

const columns = [
    { name: 'plan', type: 'String' },
    { name: 'revenue', type: 'Float64' },
]
const frame = {
    name: 'revenue',
    runId: '00000000-0000-4000-8000-000000000042',
    columns,
    rows: [
        ['Starter', 120],
        ['Growth', 480],
        ['Scale', 950],
    ],
    totalRowCount: 3,
    includedRowCount: 3,
    offset: 0,
    nextOffset: null,
    truncated: false,
}

const meta: Meta<typeof ReusableWidgetDemoDataModal> = {
    title: 'Products/Notebooks/Reusable widget demo data',
    component: ReusableWidgetDemoDataModal,
    decorators: [mswDecorator({})],
    args: {
        projectId: 1,
        widgetId: '00000000-0000-4000-8000-000000000041',
        canEdit: true,
        onClose: () => undefined,
        onSaved: () => undefined,
        version: {
            id: '00000000-0000-4000-8000-000000000042',
            title: 'Revenue by plan',
            version: 2,
            operation: 'improve',
            model: null,
            artifact_url: null,
            build_status: 'ready',
            build_hash: null,
            frame_names: ['revenue'],
            input_contract: [{ slot: 'revenue', sourceName: 'revenue', columns, schemaHash: '' }],
            security_review: null,
            has_demo_data: true,
            created_at: '2026-01-01T00:00:00Z',
        },
    },
    parameters: {
        testOptions: { snapshotTargetSelector: '.LemonModal' },
        msw: {
            mocks: {
                get: { '/api/projects/:team_id/notebook_widgets/:id/frames/:frame_name/': [200, frame] },
            },
        },
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const SavedRows: Story = {}
export const HistoricalVersion: Story = { args: { canEdit: false } }
export const LoadError: Story = {
    parameters: {
        msw: { mocks: { get: { '/api/projects/:team_id/notebook_widgets/:id/frames/:frame_name/': [500, {}] } } },
    },
}
