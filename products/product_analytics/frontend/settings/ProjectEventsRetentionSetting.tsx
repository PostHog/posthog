import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { urls } from 'scenes/urls'

import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'
import { EventsRetentionWindowForm } from './EventsRetentionWindowForm'

export function ProjectEventsRetentionSetting(): JSX.Element | null {
    const { projectRetention, projectRetentionLoading } = useValues(eventsRetentionSettingsLogic)
    const { updateProjectRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!projectRetention) {
        return null
    }

    const organizationMonths = projectRetention.organization_retention_months
    const fallbackMonths = organizationMonths ?? projectRetention.default_retention_months
    const fallback =
        organizationMonths !== null
            ? `the organization's window of ${organizationMonths} months`
            : `the default window of ${fallbackMonths} months`

    return (
        <div>
            <p className="max-w-160 text-sm text-secondary mb-4">
                Choose how long this project keeps events. This replaces the window set in{' '}
                <Link to={urls.settings('organization-details', 'organization-events-retention')}>
                    organization settings
                </Link>
                . {projectRetention.project_retention_months === null && `This project uses ${fallback}. `}
                <Link to={projectRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <EventsRetentionWindowForm
                retentionMonths={projectRetention.project_retention_months}
                deleteMonthly={projectRetention.delete_monthly}
                fallbackMonths={fallbackMonths}
                minMonths={projectRetention.min_retention_months}
                maxMonths={projectRetention.max_retention_months}
                planMonths={projectRetention.plan_retention_months}
                keptBy="This project"
                removedDescription={`This project will use ${fallback}, and the organization's choice of when to delete older events.`}
                nextMonthlyCleanupOn={projectRetention.next_monthly_cleanup_on}
                nextDeletionOn={projectRetention.next_deletion_on}
                nextDeletionBefore={projectRetention.next_deletion_before}
                saving={projectRetentionLoading}
                restrictionReason={restrictionReason}
                onSave={updateProjectRetention}
                dataAttr="project-events-retention"
            />
        </div>
    )
}
