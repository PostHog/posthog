import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { SpaceResourceConfigApi } from '../generated/api.schemas'
import { SpaceScene } from './SpaceScene'

const SPACE_ID = '00000000-0000-4000-8000-000000000001'
const CANVAS_ID = '00000000-0000-4000-8000-000000000002'
const FILES = [
    {
        id: '00000000-0000-4000-8000-000000000003',
        path: 'Growth/Weekly overview',
        type: 'dashboard',
        href: '/dashboard/123',
        ref: '123',
        user_access_level: 'editor',
    },
    {
        id: '00000000-0000-4000-8000-000000000004',
        path: 'Growth/Signup to activation',
        type: 'insight',
        href: '/insights/demo0001',
        ref: 'demo0001',
        user_access_level: 'viewer',
    },
    {
        id: '00000000-0000-4000-8000-000000000005',
        path: 'Growth/Metric definitions',
        type: 'notebook',
        href: '/notebooks/demo0002',
        ref: 'demo0002',
        user_access_level: 'editor',
    },
]
const AUTHOR = {
    id: 1,
    uuid: '00000000-0000-4000-8000-000000000099',
    email: 'ada@example.com',
    first_name: 'Ada',
    last_name: '',
}
const meta: Meta = {
    title: 'Scenes-App/Tasks/Space overview',
    decorators: [mswDecorator({})],
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        mockDate: '2026-10-14 12:00:00',
        testOptions: { viewport: { width: 1280, height: 900 } },
    },
    render: (_, context) => {
        const { parameters } = context
        let config: SpaceResourceConfigApi = parameters.empty
            ? { resources: [], featured_canvas: null }
            : {
                  featured_canvas: CANVAS_ID,
                  resources: FILES.map((file, index) => ({ file_id: file.id, pinned: index < 2 })),
              }
        mswDecorator({
            get: {
                '/api/projects/:team_id/task_channels/:id/': [
                    200,
                    {
                        id: SPACE_ID,
                        name: 'growth',
                        starred: true,
                        channel_type: 'public',
                        created_by: AUTHOR,
                        repositories: [],
                        system_role: null,
                    },
                ],
                '/api/projects/:team_id/task_channels/:id/resources/': () =>
                    parameters.unavailable ? [500, {}] : [200, config],
                '/api/projects/:team_id/task_channels/': [200, []],
                '/api/projects/:team_id/tasks/': [200, { results: [], next: null }],
                '/api/projects/:team_id/file_system/': [200, { results: FILES, next: null, count: FILES.length }],
                '/api/projects/:team_id/canvases/': [
                    200,
                    {
                        results: parameters.empty
                            ? []
                            : [
                                  {
                                      id: CANVAS_ID,
                                      name: 'Growth overview',
                                      description: 'Goals, weekly results, and the context behind our metrics.',
                                      kind: 'freeform',
                                      channel: SPACE_ID,
                                      template_id: 'blank',
                                      pinned: true,
                                      pinned_at: '2026-10-14T10:00:00Z',
                                      created_by: AUTHOR,
                                      created_at: '2026-10-14T10:00:00Z',
                                      updated_at: '2026-10-14T10:00:00Z',
                                      url: `/canvases/${CANVAS_ID}`,
                                      current_version_id: null,
                                      published_build_id: null,
                                  },
                              ],
                        next: null,
                        count: 1,
                    },
                ],
            },
            put: {
                '/api/projects/:team_id/task_channels/:id/resources/': async ({ request }) => {
                    config = (await request.json()) as SpaceResourceConfigApi
                    return [200, config]
                },
            },
        })(() => <></>, context)
        return (
            <div className="Today p-4" data-quill>
                <SpaceScene id={SPACE_ID} />
            </div>
        )
    },
}
export default meta
type Story = StoryObj
export const Overview: Story = {}
export const Empty: Story = { parameters: { empty: true } }
export const Unavailable: Story = { parameters: { unavailable: true } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-130">
                <Story />
            </div>
        ),
    ],
}
