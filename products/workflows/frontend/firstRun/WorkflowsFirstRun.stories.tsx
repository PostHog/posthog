import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import { globalTemplates, projectThatSends } from './firstRunStoryFixtures'

const meta: Meta = {
    component: App,
    title: 'Products/Workflows/First run gallery',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-05',
        pageUrl: urls.workflows(),
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN],
        testOptions: { viewport: { width: 1440, height: 2400 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': {
                    email_sending_suspended: false,
                    email_sending_suspended_at: null,
                    email_sending_suspension_reason: '',
                },
                '/api/projects/:team_id/hog_flow_templates/': toPaginatedResponse(globalTemplates),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const ProjectWithSignups: Story = {
    decorators: [mswDecorator(projectThatSends(['signed_up', '$pageview', '$feature_view']))],
}

export const ProjectWithOnlyPageviews: Story = {
    decorators: [mswDecorator(projectThatSends(['$pageview']))],
}

export const ProjectWithNoEvents: Story = {
    decorators: [mswDecorator(projectThatSends([]))],
    render: function ProjectWithNoEvents(): JSX.Element {
        useMountedLogic(teamLogic)
        useEffect(() => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: false })
        }, [])
        return <App />
    },
}

// A docked side panel leaves the scene about 520px wide on a laptop. This viewport gives the scene the same width.
export const ProjectWithSignupsInANarrowScene: Story = {
    decorators: [mswDecorator(projectThatSends(['signed_up', '$pageview', '$feature_view']))],
    parameters: { testOptions: { viewport: { width: 552, height: 2400 } } },
}
