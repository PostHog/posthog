import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { BillingPlan } from '~/types'

import type {
    EventsRetentionApi,
    EventsRetentionImpactApi,
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
    planMonths?: number
    grandfathered?: boolean
    billingPlan?: BillingPlan
}

const impactMock = ({ request }: { request: Request }): EventsRetentionImpactApi => {
    const months = Number(new URL(request.url).searchParams.get('retention_months'))
    return { retention_months: months, events_deleted: Math.round(1_200_000 / months) }
}

const retentionMocks = ({
    organizationMonths = null,
    projectMonths = null,
    planMonths = 36,
    grandfathered = false,
    billingPlan = BillingPlan.Boost,
}: RetentionMockOptions): ReturnType<typeof mswDecorator> => {
    const defaultMonths = grandfathered ? planMonths : Math.min(planMonths, 24)
    const organization: OrganizationEventsRetentionApi = {
        organization_retention_months: organizationMonths,
        default_retention_months: defaultMonths,
        default_is_grandfathered: grandfathered,
        plan_retention_months: planMonths,
        min_retention_months: 1,
        max_retention_months: planMonths,
        retention_months_choices: [1, 3, 12, 24, 60, 84].filter((months) => months <= planMonths),
        next_monthly_cleanup_on: '2026-11-03',
    }
    const project: EventsRetentionApi = {
        ...organization,
        retention_months: Math.min(planMonths, projectMonths ?? organizationMonths ?? defaultMonths),
        retained_from: '2024-11-01',
        docs_url: 'https://posthog.com/docs/data/events-retention',
        project_retention_months: projectMonths,
        next_deletion_on: null,
        next_deletion_before: null,
        scheduled_pass_on: '2027-02-03',
        first_pass_on: '2027-02-03',
        default_period_deletes: true,
    }
    return mswDecorator({
        get: {
            '/api/projects/:team_id/events_retention/': project,
            '/api/organizations/:organization_id/events_retention_setting/': organization,
            '/api/billing/': { ...billingJson, billing_plan: billingPlan },
            '/api/projects/:team_id/events_retention/impact/': impactMock,
            '/api/organizations/:organization_id/events_retention_setting/impact/': impactMock,
        },
    })
}

export const OrganizationWithoutWindow: Story = {
    render: () => <OrganizationEventsRetentionSetting />,
    decorators: [retentionMocks({})],
}

export const OrganizationWithWindow: Story = {
    render: () => <OrganizationEventsRetentionSetting />,
    decorators: [retentionMocks({ organizationMonths: 12 })],
}

export const OrganizationOnGrandfatheredPlan: Story = {
    render: () => <OrganizationEventsRetentionSetting />,
    decorators: [retentionMocks({ planMonths: 84, grandfathered: true, billingPlan: BillingPlan.Paid })],
}

export const OrganizationOnFreePlan: Story = {
    render: () => <OrganizationEventsRetentionSetting />,
    decorators: [retentionMocks({ planMonths: 12, billingPlan: BillingPlan.Free })],
}

export const ProjectUsingOrganizationWindow: Story = {
    render: () => <ProjectEventsRetentionSetting />,
    decorators: [retentionMocks({ organizationMonths: 12 })],
}

export const ProjectWithOwnWindow: Story = {
    render: () => <ProjectEventsRetentionSetting />,
    decorators: [retentionMocks({ organizationMonths: 24, projectMonths: 12 })],
}

export const ProjectWithOwnPeriodAbovePlan: Story = {
    render: () => <ProjectEventsRetentionSetting />,
    decorators: [retentionMocks({ planMonths: 24, projectMonths: 36, billingPlan: BillingPlan.Paid })],
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
