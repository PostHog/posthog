import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { EventsRetentionPeriodForm } from './EventsRetentionPeriodForm'
import { EventsRetentionPlanNote } from './EventsRetentionPlanNote'
import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'

export function OrganizationEventsRetentionSetting(): JSX.Element | null {
    const {
        projectRetention,
        organizationRetention,
        organizationRetentionLoading,
        organizationImpact,
        organizationImpactLoading,
    } = useValues(eventsRetentionSettingsLogic)
    const { updateOrganizationRetention, loadOrganizationImpact } = useActions(eventsRetentionSettingsLogic)
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
            <EventsRetentionPeriodForm
                retentionMonths={organizationRetention.organization_retention_months}
                defaultMonths={organizationRetention.default_retention_months}
                defaultSource="plan"
                monthlyDefaultMonths={null}
                maxMonths={organizationRetention.max_retention_months}
                choiceMonths={organizationRetention.retention_months_choices}
                planMonths={organizationRetention.plan_retention_months}
                scope="Events in projects without their own custom events retention"
                overrideNote="Projects with their own custom events retention policy will override this organization level policy."
                nextMonthlyCleanupOn={organizationRetention.next_monthly_cleanup_on}
                passSchedule={null}
                saving={organizationRetentionLoading}
                restrictionReason={restrictionReason}
                onSave={updateOrganizationRetention}
                impact={organizationImpact}
                impactLoading={organizationImpactLoading}
                onCountImpact={loadOrganizationImpact}
                dataAttr="organization-events-retention"
            />
        </div>
    )
}
