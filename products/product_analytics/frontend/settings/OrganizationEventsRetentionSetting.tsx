import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { EventsRetentionPeriodSelect } from './EventsRetentionPeriodSelect'
import { EventsRetentionPlanNote } from './EventsRetentionPlanNote'
import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'

export function OrganizationEventsRetentionSetting(): JSX.Element | null {
    const { projectRetention, organizationRetention, organizationRetentionLoading } =
        useValues(eventsRetentionSettingsLogic)
    const { updateOrganizationRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!projectRetention || !organizationRetention) {
        return null
    }

    return (
        <div>
            <p className="max-w-160 text-sm text-secondary mb-2">
                Choose how long projects in this organization keep events. A project can set its own period instead.{' '}
                <Link to={projectRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <EventsRetentionPlanNote plan={organizationRetention} />
            <EventsRetentionPeriodSelect
                retentionMonths={organizationRetention.organization_retention_months}
                defaultLabel="Default"
                defaultMonths={organizationRetention.default_retention_months}
                monthlyDefaultMonths={null}
                choices={organizationRetention.retention_months_choices}
                minMonths={organizationRetention.min_retention_months}
                maxMonths={organizationRetention.max_retention_months}
                planMonths={organizationRetention.plan_retention_months}
                nextMonthlyCleanupOn={organizationRetention.next_monthly_cleanup_on}
                passSchedule={null}
                level="organization"
                scope="Events in projects without their own period"
                owner="this organization"
                note="Projects without their own period use this."
                saving={organizationRetentionLoading}
                restrictionReason={restrictionReason}
                onSave={updateOrganizationRetention}
                dataAttr="organization-events-retention"
            />
        </div>
    )
}
