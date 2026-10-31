import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { urls } from 'scenes/urls'

import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'
import { EventsRetentionFallback, EventsRetentionWindowForm } from './EventsRetentionWindowForm'

export function ProjectEventsRetentionSetting(): JSX.Element | null {
    const { projectRetention, projectRetentionLoading } = useValues(eventsRetentionSettingsLogic)
    const { updateProjectRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!projectRetention) {
        return null
    }

    const organizationMonths = projectRetention.organization_retention_months
    const fallback: EventsRetentionFallback =
        organizationMonths !== null
            ? {
                  months: organizationMonths,
                  deleteMonthly: projectRetention.organization_delete_monthly,
                  isSet: true,
                  description: `the organization's window of ${organizationMonths} months`,
              }
            : {
                  months: projectRetention.default_retention_months,
                  deleteMonthly: false,
                  isSet: false,
                  description: `the default window of ${projectRetention.default_retention_months} months`,
              }

    return (
        <div>
            <p className="max-w-160 text-sm text-secondary mb-4">
                Choose how long this project keeps events. This replaces the window set in{' '}
                <Link to={urls.settings('organization-details', 'organization-events-retention')}>
                    organization settings
                </Link>
                .{' '}
                <Link to={projectRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <EventsRetentionWindowForm
                retentionMonths={projectRetention.project_retention_months}
                deleteMonthly={projectRetention.delete_monthly}
                fallback={fallback}
                minMonths={projectRetention.min_retention_months}
                maxMonths={projectRetention.max_retention_months}
                planMonths={projectRetention.plan_retention_months}
                keptBy="This project"
                nextMonthlyCleanupOn={projectRetention.next_monthly_cleanup_on}
                passSchedule={projectRetention}
                saving={projectRetentionLoading}
                restrictionReason={restrictionReason}
                onSave={updateProjectRetention}
                dataAttr="project-events-retention"
            />
        </div>
    )
}
