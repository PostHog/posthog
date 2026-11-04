import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { EventsRetentionPeriodForm } from './EventsRetentionPeriodForm'
import { EventsRetentionPlanNote } from './EventsRetentionPlanNote'
import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'

export function ProjectEventsRetentionSetting(): JSX.Element | null {
    const { projectRetention, projectRetentionLoading, projectImpact, projectImpactLoading } =
        useValues(eventsRetentionSettingsLogic)
    const { updateProjectRetention, loadProjectImpact } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!projectRetention) {
        return null
    }

    const organizationMonths =
        projectRetention.organization_retention_months === null
            ? null
            : Math.min(projectRetention.organization_retention_months, projectRetention.plan_retention_months)

    return (
        <div>
            <p className="max-w-160 text-sm text-secondary mb-2">
                Choose how long this project keeps events.{' '}
                <Link to={projectRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <EventsRetentionPlanNote plan={projectRetention} />
            <EventsRetentionPeriodForm
                retentionMonths={projectRetention.project_retention_months}
                defaultMonths={organizationMonths ?? projectRetention.default_retention_months}
                defaultSource="organization"
                monthlyDefaultMonths={projectRetention.organization_retention_months}
                maxMonths={projectRetention.max_retention_months}
                choiceMonths={projectRetention.retention_months_choices}
                planMonths={projectRetention.plan_retention_months}
                scope="Events in this project"
                overrideNote="This project's custom events retention replaces the organization's events retention."
                nextMonthlyCleanupOn={projectRetention.next_monthly_cleanup_on}
                passSchedule={projectRetention}
                saving={projectRetentionLoading}
                restrictionReason={restrictionReason}
                onSave={updateProjectRetention}
                impact={projectImpact}
                impactLoading={projectImpactLoading}
                onCountImpact={loadProjectImpact}
                dataAttr="project-events-retention"
            />
        </div>
    )
}
