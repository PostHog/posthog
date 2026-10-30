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

interface RetentionMockOptions {
    organizationMonths?: number | null
    projectMonths?: number | null
    deleteMonthly?: boolean
    nextDeletionOn?: string | null
    nextDeletionBefore?: string | null
}

const retentionMocks = ({
    organizationMonths = null,
    projectMonths = null,
    deleteMonthly = false,
    nextDeletionOn = null,
    nextDeletionBefore = null,
}: RetentionMockOptions): ReturnType<typeof mswDecorator> => {
    const organization: OrganizationEventsRetentionApi = {
        organization_retention_months: organizationMonths,
        organization_delete_monthly: projectMonths === null && deleteMonthly,
        plan_retention_months: 36,
        default_retention_months: 24,
        min_retention_months: 1,
        max_retention_months: 36,
        next_monthly_cleanup_on: '2026-11-03',
    }
    const project: EventsRetentionApi = {
        ...organization,
        retention_months: projectMonths ?? organizationMonths ?? 36,
        retained_from: '2024-11-01',
        docs_url: 'https://posthog.com/docs/data/events-retention',
        project_retention_months: projectMonths,
        delete_monthly: deleteMonthly,
        next_deletion_on: nextDeletionOn,
        next_deletion_before: nextDeletionBefore,
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
    decorators: [retentionMocks({})],
}

export const OrganizationWithWindow: Story = {
    render: () => <OrganizationEventsRetentionSetting />,
    decorators: [
        retentionMocks({
            organizationMonths: 24,
            deleteMonthly: true,
            nextDeletionOn: '2026-11-03',
            nextDeletionBefore: '2024-11-01',
        }),
    ],
}

export const ProjectUsingOrganizationWindow: Story = {
    render: () => <ProjectEventsRetentionSetting />,
    decorators: [retentionMocks({ organizationMonths: 24 })],
}

export const ProjectWithDeletionScheduled: Story = {
    render: () => <ProjectEventsRetentionSetting />,
    decorators: [retentionMocks({ nextDeletionOn: '2027-02-03', nextDeletionBefore: '2025-02-01' })],
}

export const ProjectWithOwnWindow: Story = {
    render: () => <ProjectEventsRetentionSetting />,
    decorators: [
        retentionMocks({
            organizationMonths: 24,
            projectMonths: 12,
            nextDeletionOn: '2027-02-03',
            nextDeletionBefore: '2026-02-01',
        }),
    ],
}
