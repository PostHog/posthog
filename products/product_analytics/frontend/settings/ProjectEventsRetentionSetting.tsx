import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { urls } from 'scenes/urls'

import { EventsRetentionPlanNote } from './EventsRetentionPlanNote'
import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'
import { EventsRetentionWindowForm } from './EventsRetentionWindowForm'

export function ProjectEventsRetentionSetting(): JSX.Element | null {
    const { projectRetention, projectRetentionLoading } = useValues(eventsRetentionSettingsLogic)
    const { updateProjectRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!projectRetention) {
        return null
    }

    const organizationMonths =
        projectRetention.organization_retention_months === null
            ? null
            : Math.min(projectRetention.organization_retention_months, projectRetention.plan_retention_months)
    const hasOrganizationWindow = organizationMonths !== null

    return (
        <div>
            <p className="max-w-160 text-sm text-secondary mb-2">
                Choose how long this project keeps events.{' '}
                {hasOrganizationWindow && (
                    <>
                        This replaces the window set in{' '}
                        <Link to={urls.settings('organization-details', 'organization-events-retention')}>
                            organization settings
                        </Link>
                        .{' '}
                    </>
                )}
                <Link to={projectRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <EventsRetentionPlanNote plan={projectRetention} />
            <EventsRetentionWindowForm
                retentionMonths={projectRetention.project_retention_months}
                defaultMonths={organizationMonths ?? projectRetention.default_retention_months}
                defaultIsOrganizationWindow={hasOrganizationWindow}
                minMonths={projectRetention.min_retention_months}
                maxMonths={projectRetention.max_retention_months}
                planMonths={projectRetention.plan_retention_months}
                scope="Events in this project"
                overrideNote={
                    hasOrganizationWindow
                        ? "This project's custom events retention replaces the organization's events retention."
                        : null
                }
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
