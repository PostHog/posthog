import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'
import { EventsRetentionWindowForm } from './EventsRetentionWindowForm'

export function OrganizationEventsRetentionSetting(): JSX.Element | null {
    const { projectRetention, organizationRetention, organizationRetentionLoading } =
        useValues(eventsRetentionSettingsLogic)
    const { updateOrganizationRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!projectRetention || !organizationRetention) {
        return null
    }

    const defaultMonths = organizationRetention.default_retention_months
    const projectUsesThisWindow = projectRetention.project_retention_months === null

    return (
        <div>
            <p className="max-w-160 text-sm text-secondary mb-4">
                Choose how long projects in this organization keep events. A project can set its own window instead.{' '}
                {organizationRetention.organization_retention_months === null &&
                    `No window is set, so projects use the default window of ${defaultMonths} months. `}
                <Link to={projectRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <EventsRetentionWindowForm
                retentionMonths={organizationRetention.organization_retention_months}
                deleteMonthly={organizationRetention.organization_delete_monthly}
                fallbackMonths={defaultMonths}
                minMonths={organizationRetention.min_retention_months}
                maxMonths={organizationRetention.max_retention_months}
                planMonths={organizationRetention.plan_retention_months}
                keptBy="Every project without its own window"
                removedDescription={`Projects without their own window will use the default window of ${defaultMonths} months, and older events will be deleted every 3 months.`}
                nextMonthlyCleanupOn={organizationRetention.next_monthly_cleanup_on}
                nextDeletionOn={projectUsesThisWindow ? projectRetention.next_deletion_on : null}
                nextDeletionBefore={projectUsesThisWindow ? projectRetention.next_deletion_before : null}
                saving={organizationRetentionLoading}
                restrictionReason={restrictionReason}
                onSave={updateOrganizationRetention}
                dataAttr="organization-events-retention"
            />
        </div>
    )
}
