import { Decorator, Meta, StoryObj } from '@storybook/react'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { WorkflowViewApi, WorkflowViewCreateApi, WorkflowViewUpdateApi } from '../../generated/api.schemas'
import { OPTIONAL_COLUMNS } from './workflowListLabels'
import { FIXTURE_METRICS, FIXTURE_WORKFLOWS, paginated } from './workflowsListV2Fixtures'

const workflowsUrl = (params: Record<string, string> = {}): string => {
    const search = new URLSearchParams(params).toString()
    return search ? `${urls.workflows()}?${search}` : urls.workflows()
}

const allColumnsUrl = (): string => workflowsUrl({ columns: OPTIONAL_COLUMNS.join(',') })

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Workflows/List v2',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-25',
        pageUrl: workflowsUrl(),
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_LIST_V2],
        testOptions: { viewport: { width: 1440, height: 900 }, snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                // The empty-state gate counts workflows before the scene renders, and the flag-off list
                // reads their steps.
                '/api/projects/:team_id/hog_flows/': paginated(
                    FIXTURE_WORKFLOWS.map((workflow) => ({ ...workflow, actions: [], edges: [] }))
                ),
                // The server search finds nothing beyond the names and descriptions the list matches itself.
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) => [
                    200,
                    paginated(new URL(request.url).searchParams.has('search') ? [] : FIXTURE_WORKFLOWS),
                ],
                '/api/projects/:team_id/hog_flows/metrics/global/': FIXTURE_METRICS,
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': {
                    email_sending_suspended: false,
                    email_sending_suspended_at: null,
                    email_sending_suspension_reason: '',
                },
                '/api/projects/:team_id/hog_flow_templates/': paginated([]),
                '/api/projects/:team_id/file_system/unfiled/': { count: 0 },
                '/api/projects/:team_id/file_system/': paginated([]),
                '/api/projects/:team_id/workflow_views/': paginated([]),
            },
            post: {
                '/api/projects/:team_id/workflow_views/initialize/': () => [403, {}],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {}

export const AllColumns: Story = {
    parameters: { pageUrl: allColumnsUrl() },
}

export const MetricsLoading: Story = {
    parameters: { pageUrl: allColumnsUrl(), testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/metrics/global/': () => new Promise(() => {}),
            },
        }),
    ],
}

export const MetricsUnavailable: Story = {
    parameters: { pageUrl: allColumnsUrl() },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/metrics/global/': () => [500, { detail: 'Server error' }],
            },
        }),
    ],
}

export const NoMatches: Story = {
    parameters: { pageUrl: workflowsUrl({ q: 'status:active', text: 'nothing like this' }) },
}

export const ServerSearchFailed: Story = {
    parameters: { pageUrl: workflowsUrl({ text: 'renewal' }) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) =>
                    new URL(request.url).searchParams.has('search')
                        ? [500, { detail: 'Server error' }]
                        : [200, paginated(FIXTURE_WORKFLOWS)],
            },
        }),
    ],
}

export const Loading: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => new Promise(() => {}),
            },
        }),
    ],
}

export const LoadError: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => [500, { detail: 'Server error' }],
            },
        }),
    ],
}

export const NarrowScene: Story = {
    parameters: {
        pageUrl: workflowsUrl({ q: 'kind:messaging -status:archived', text: 'reminder' }),
        // The navigation collapses at this width, which leaves a 520px scene.
        testOptions: { viewport: { width: 552, height: 900 } },
    },
}

export const FlagOff: Story = {
    parameters: { featureFlags: [] },
}

const withSavedViews: Decorator = (Story, context) => {
    const defaultView: WorkflowViewApi = {
        id: '00000000-0000-4000-8000-000000000001',
        name: 'My workflows',
        state: { filters: [{ facet: 'createdBy', value: 'me', negated: false }], text: '', columns: ['owner'] },
        version: 1,
        default_key: 'my-workflows',
        deleted: false,
        created_at: '2026-10-07T00:00:00Z',
        updated_at: '2026-10-07T00:00:00Z',
        user_access_level: 'editor',
    }
    let nextId = 10
    let views: WorkflowViewApi[] = [
        defaultView,
        {
            ...defaultView,
            id: '00000000-0000-4000-8000-000000000002',
            name: 'Renewal reminders',
            default_key: null,
            state: {
                filters: [{ facet: 'kind', value: 'messaging', negated: false }],
                text: 'renewal',
                columns: ['owner', 'health'],
            },
        },
        {
            ...defaultView,
            id: '00000000-0000-4000-8000-000000000003',
            name: 'Automations',
            default_key: null,
            state: {
                filters: [{ facet: 'kind', value: 'automation', negated: false }],
                text: '',
                columns: ['trigger'],
            },
        },
    ]
    return mswDecorator({
        get: {
            '/api/projects/:team_id/workflow_views/': () => [200, paginated(views.filter((view) => !view.deleted))],
            '/api/projects/:team_id/workflow_views/:id/': ({ params }) => {
                const view = views.find((candidate) => candidate.id === params.id && !candidate.deleted)
                return view ? [200, view] : [404, { detail: 'View not found' }]
            },
        },
        post: {
            '/api/projects/:team_id/workflow_views/': async ({ request }) => {
                const body = (await request.json()) as WorkflowViewCreateApi
                const view: WorkflowViewApi = {
                    ...defaultView,
                    ...body,
                    id: `00000000-0000-4000-8000-${String(nextId++).padStart(12, '0')}`,
                    default_key: null,
                }
                views = [...views, view]
                return [201, view]
            },
            '/api/projects/:team_id/workflow_views/initialize/': () => [
                200,
                views.find((view) => view.default_key === 'my-workflows') ?? defaultView,
            ],
            '/api/projects/:team_id/workflow_views/restore_default/': () => {
                const previous = views.find((view) => view.default_key === 'my-workflows')
                const restored = previous?.deleted
                    ? { ...defaultView, version: previous.version + 1 }
                    : (previous ?? defaultView)
                views = [...views.filter((view) => view.default_key !== 'my-workflows'), restored]
                return [200, restored]
            },
        },
        patch: {
            '/api/projects/:team_id/workflow_views/:id/': async ({ request, params }) => {
                const body = (await request.json()) as WorkflowViewUpdateApi
                const previous = views.find((view) => view.id === params.id && !view.deleted)
                if (!previous) {
                    return [404, { detail: 'View not found' }]
                }
                if (previous.version !== body.version) {
                    return [409, { detail: 'View changed' }]
                }
                const updated = { ...previous, ...body, version: previous.version + 1 }
                views = views.map((view) => (view.id === previous.id ? updated : view))
                return [200, updated]
            },
        },
        delete: {
            '/api/projects/:team_id/workflow_views/:id/': ({ request, params }) => {
                const previous = views.find((view) => view.id === params.id && !view.deleted)
                if (!previous) {
                    return [404, { detail: 'View not found' }]
                }
                if (String(previous.version) !== new URL(request.url).searchParams.get('version')) {
                    return [409, { detail: 'View changed' }]
                }
                views = previous.default_key
                    ? views.map((view) =>
                          view.id === previous.id ? { ...view, deleted: true, version: view.version + 1 } : view
                      )
                    : views.filter((view) => view.id !== previous.id)
                return [204]
            },
        },
    })(Story, context)
}

function SavedViewsStoryApp(): JSX.Element {
    useEffect(() => posthog.reloadFeatureFlags(), [])
    return <App />
}

export const SavedViews: Story = {
    render: () => <SavedViewsStoryApp />,
    parameters: { featureFlags: [FEATURE_FLAGS.WORKFLOWS_LIST_V2] },
    decorators: [withSavedViews],
}

export const SavedViewsNarrow: Story = {
    render: () => <SavedViewsStoryApp />,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_LIST_V2],
        pageUrl: workflowsUrl({
            view: '00000000-0000-4000-8000-000000000002',
            q: 'kind:messaging',
            text: '',
            columns: 'owner,health',
        }),
        testOptions: { viewport: { width: 552, height: 900 } },
    },
    decorators: [withSavedViews],
}
