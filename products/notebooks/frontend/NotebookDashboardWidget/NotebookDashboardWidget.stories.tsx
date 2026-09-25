import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/react'
import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, DashboardBasicType, DashboardPlacement, DashboardTile } from '~/types'

import { DashboardWidgetItem } from 'products/dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem'

import { notebookWidgetDashboardLogic } from '../NotebookNodeGeneratedWidget/notebookWidgetDashboardLogic'
import { NotebookWidgetDashboardModal } from '../NotebookNodeGeneratedWidget/NotebookWidgetDashboardModal'
import { NotebookDashboardWidget } from './NotebookDashboardWidget'

const snapshot = {
    id: '00000000-0000-4000-8000-000000000042',
    node_id: 'revenue-widget',
    version_id: '00000000-0000-4000-8000-000000000041',
    created_at: '2026-09-01T10:00:00Z',
    frame_names: ['revenue'],
    input_bindings: {},
    input_contract: [
        {
            slot: 'revenue',
            sourceName: 'revenue',
            columns: [
                { name: 'plan', type: 'String' },
                { name: 'revenue', type: 'Float64' },
            ],
            schemaHash: '',
        },
    ],
    artifact_url: `${window.location.origin}/notebook-dashboard-widget.html`,
    build_hash: 'a'.repeat(64),
    security_review: {
        severity: 'none',
        summary: 'No security issues found.',
        findings: [],
        model: 'claude-haiku-4-5',
        review_version: '1',
        reviewed_at: '2026-09-01T10:00:00Z',
    },
}

const meta: Meta<typeof NotebookDashboardWidget> = {
    title: 'Products/Notebooks/Dashboard widget',
    component: NotebookDashboardWidget,
    render: (args) => (
        <DashboardWidgetItem
            className="h-full"
            tile={
                {
                    id: args.tileId,
                    widget: {
                        id: '00000000-0000-4000-8000-000000000044',
                        widget_type: 'notebook_widget',
                        name: 'Revenue by plan',
                        description: '',
                        config: args.config,
                    },
                } as DashboardTile
            }
            placement={DashboardPlacement.Dashboard}
            result={args.result}
            loading={args.loading}
            onRefresh={() => undefined}
            onUpdateWidgetTile={() => undefined}
            onConfigPublished={args.onConfigPublished}
            canEditDashboard={!!args.onConfigPublished}
            showEditingControls
        />
    ),
    decorators: [
        mswDecorator({}),
        (Story) => (
            <div className="h-[520px] w-full max-w-3xl">
                <Story />
            </div>
        ),
    ],
    args: {
        tileId: 42,
        config: { notebookShortId: 'example', snapshotId: snapshot.id },
        result: {},
        loading: false,
        onConfigPublished: () => undefined,
    },
    parameters: {
        mockDate: '2026-09-01T10:30:00Z',
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/notebooks/:short_id/widget_snapshots/:snapshot_id/': snapshot,
                    '/api/projects/:team_id/notebooks/:short_id/widget_snapshots/:snapshot_id/frames/:frame_name/': {
                        name: 'revenue',
                        runId: '00000000-0000-4000-8000-000000000043',
                        columns: snapshot.input_contract[0].columns,
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
                    },
                    '/api/projects/:team_id/notebooks/:short_id/widgets/:node_id/source/': {
                        source: 'export default function RevenueWidget() { /* Example widget source */ }',
                    },
                },
            },
        },
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const SavedResults: Story = {}
export const Empty: Story = { args: { config: {} }, render: (args) => <NotebookDashboardWidget {...args} /> }
export const ReadOnly: Story = { args: { onConfigPublished: undefined } }
export const AccessDenied: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/notebooks/:short_id/widget_snapshots/:snapshot_id/': [
                        403,
                        { detail: 'Access denied' },
                    ],
                },
            },
        },
    },
}

function AddToDashboardExample(): JSX.Element {
    const props = {
        notebookShortId: 'example',
        nodeId: 'revenue-widget',
        versionId: snapshot.version_id,
        title: 'Revenue by plan',
        persistNotebook: async () => {},
    }
    const { open } = useActions(notebookWidgetDashboardLogic(props))
    return (
        <>
            <LemonButton onClick={open}>Add to dashboard</LemonButton>
            <NotebookWidgetDashboardModal {...props} />
        </>
    )
}

export const AddToDashboard: Story = {
    render: () => <AddToDashboardExample />,
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/dashboards/': {
                        results: Array.from(
                            { length: 250 },
                            (_, index): DashboardBasicType => ({
                                id: index + 1,
                                name:
                                    index === 0
                                        ? 'Activation overview'
                                        : index === 1
                                          ? 'Board review'
                                          : index === 249
                                            ? 'Revenue overview'
                                            : `Metrics report ${index + 1}`,
                                description:
                                    index === 0
                                        ? 'Signups, onboarding, and activation across the product.'
                                        : index === 249
                                          ? 'Conversion from trial to paid plans.'
                                          : '',
                                created_by: {
                                    id: index + 1,
                                    uuid: `example-creator-${index + 1}`,
                                    distinct_id: `example-creator-${index + 1}`,
                                    first_name:
                                        index === 0 ? 'Avery Stone' : index === 249 ? 'Jules Parker' : 'Morgan Reed',
                                    email:
                                        index === 0
                                            ? 'avery@example.com'
                                            : index === 249
                                              ? 'jules@example.com'
                                              : 'morgan@example.com',
                                },
                                created_at: '2026-01-01T00:00:00Z',
                                pinned: index === 0,
                                deleted: false,
                                is_shared: false,
                                last_accessed_at: null,
                                creation_mode: 'default',
                                user_access_level: index === 1 ? AccessControlLevel.Viewer : AccessControlLevel.Editor,
                            })
                        ),
                        next: null,
                        count: 250,
                    },
                },
            },
        },
        testOptions: { snapshotTargetSelector: 'body', viewportWidths: ['narrow', 'wide'] },
    },
    play: async () => {
        const screen = within(document.body)
        fireEvent.click(screen.getByText('Add to dashboard'))
        await waitFor(() => {
            if (screen.getByText('Choose a dashboard').closest('button')?.classList.contains('LemonButton--loading')) {
                throw new Error('Dashboards are still loading')
            }
        })
        fireEvent.click(await screen.findByText('Choose a dashboard'))
        await screen.findByText('Activation overview')
    },
}

export const SearchDashboardByCreator: Story = {
    ...AddToDashboard,
    play: async (context) => {
        await AddToDashboard.play?.(context)
        fireEvent.change(within(document.body).getByPlaceholderText('Search by name, description, or creator'), {
            target: { value: 'Jules' },
        })
    },
}
