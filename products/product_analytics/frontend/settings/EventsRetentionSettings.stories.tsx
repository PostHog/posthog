import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type {
    EventsRetentionApi,
    OrganizationEventsRetentionApi,
} from 'products/product_analytics/frontend/generated/api.schemas'

import { OrganizationEventsRetentionSetting } from './OrganizationEventsRetentionSetting'
import { ProjectEventsRetentionSetting } from './ProjectEventsRetentionSetting'

const meta: Meta = {
    title: 'Scenes-App/Settings/Events Retention',
    parameters: {
        mockDate: '2026-11-01',
    },
}
export default meta
type Story = StoryObj

const retentionMocks = (
    organizationMonths: number | null,
    projectMonths: number | null
): ReturnType<typeof mswDecorator> => {
    const organization: OrganizationEventsRetentionApi = {
        organization_retention_months: organizationMonths,
        default_retention_months: 36,
        default_is_grandfathered: true,
        plan_retention_months: 36,
        min_retention_months: 1,
        max_retention_months: 36,
        retention_months_choices: [1, 3, 12, 24, 36, 60, 84],
        next_monthly_cleanup_on: '2026-11-03',
    }
    const project: EventsRetentionApi = {
        ...organization,
        retention_months: projectMonths ?? organizationMonths ?? 36,
        retained_from: '2024-11-01',
        docs_url: 'https://posthog.com/docs/data/events-retention',
        project_retention_months: projectMonths,
        next_deletion_on: null,
        next_deletion_before: null,
        scheduled_pass_on: null,
        first_pass_on: '2027-02-03',
        default_period_deletes: false,
    }
    return mswDecorator({
        get: {
            '/api/projects/:team_id/events_retention/': project,
            '/api/organizations/:organization_id/events_retention_setting/': organization,
        },
    })
}

export const OrganizationWithoutWindow: Story = {
    render: () => <OrganizationEventsRetentionSetting />,
    decorators: [retentionMocks(null, null)],
}

export const OrganizationWithWindow: Story = {
    render: () => <OrganizationEventsRetentionSetting />,
    decorators: [retentionMocks(24, null)],
}

export const ProjectUsingOrganizationWindow: Story = {
    render: () => <ProjectEventsRetentionSetting />,
    decorators: [retentionMocks(24, null)],
}

export const ProjectWithOwnWindow: Story = {
    render: () => <ProjectEventsRetentionSetting />,
    decorators: [retentionMocks(24, 12)],
}
