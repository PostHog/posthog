import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

const GROUP_TYPES = [
    {
        group_type: 'account',
        group_type_index: 0,
        name_singular: null,
        name_plural: null,
        detail_dashboard: null,
        default_columns: null,
        created_at: '2025-03-18T15:45:01.907Z',
    },
    {
        group_type: 'workflow_run',
        group_type_index: 1,
        name_singular: null,
        name_plural: null,
        detail_dashboard: null,
        default_columns: null,
        created_at: '2026-09-28T16:55:09.917Z',
    },
]

const GROUPS_QUERY_RESPONSE = {
    columns: ['group_name', 'created_at'],
    types: ['tuple', 'datetime'],
    results: [
        [{ display_name: 'acme/webapp/36453437397', key: 'acme/webapp/36453437397' }, '2026-10-28T09:12:44Z'],
        [{ display_name: 'acme/webapp/36450112903', key: 'acme/webapp/36450112903' }, '2026-10-28T07:03:12Z'],
        [{ display_name: 'acme/webapp/36441999120', key: 'acme/webapp/36441999120' }, '2026-10-27T18:40:51Z'],
    ],
    hogql: '',
    hasMore: false,
    limit: 100,
    offset: 0,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/People/Groups',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-29',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/': {
                    ...MOCK_DEFAULT_TEAM,
                    has_group_types: true,
                    group_types: GROUP_TYPES,
                },
                '/api/projects/:team_id/groups_types/': GROUP_TYPES,
                '/api/environments/:team_id/groups_types/': GROUP_TYPES,
            },
            post: {
                '/api/environments/:team_id/query': GROUPS_QUERY_RESPONSE,
                '/api/environments/:team_id/query/': GROUPS_QUERY_RESPONSE,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// groupsModel seeds from the app context when it carries group types, so the stories override it there.
function useStoryGroupTypes(): void {
    useAvailableFeatures([AvailableFeature.GROUP_ANALYTICS])
    if (window.POSTHOG_APP_CONTEXT?.current_team) {
        window.POSTHOG_APP_CONTEXT.current_team.group_types = GROUP_TYPES as any
    }
}

export const Groups: Story = {
    render: function GroupsStory() {
        useStoryGroupTypes()
        return <App />
    },
    parameters: { pageUrl: urls.groups(0) },
}

// An auto-created group type: the origin banner says when ingestion registered it and links to the events that did.
export const GroupTypeOrigin: Story = {
    render: function GroupTypeOriginStory() {
        useStoryGroupTypes()
        return <App />
    },
    parameters: {
        pageUrl: urls.groups(1),
        testOptions: {
            waitForSelector: 'a[href*="how-to-create-groups"]',
        },
    },
}
