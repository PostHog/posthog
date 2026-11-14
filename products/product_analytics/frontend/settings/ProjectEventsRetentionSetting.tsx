import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { retentionPeriodLabel } from 'lib/utils/retentionPeriodLabel'
import { urls } from 'scenes/urls'

import { EventsRetentionPeriodSelect } from './EventsRetentionPeriodSelect'
import { EventsRetentionPlanNote } from './EventsRetentionPlanNote'
import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'

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
    const defaultMonths = organizationMonths ?? projectRetention.default_retention_months

    return (
        <div>
            <p className="max-w-160 text-sm text-secondary mb-2">
                Choose how long this project keeps events.{' '}
                <Link to={projectRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <EventsRetentionPlanNote plan={projectRetention} />
            <EventsRetentionPeriodSelect
                retentionMonths={projectRetention.project_retention_months}
                defaultLabel="Organization default"
                defaultMonths={defaultMonths}
                monthlyDefaultMonths={projectRetention.organization_retention_months}
                choices={projectRetention.retention_months_choices}
                minMonths={projectRetention.min_retention_months}
                maxMonths={projectRetention.max_retention_months}
                planMonths={projectRetention.plan_retention_months}
                nextMonthlyCleanupOn={projectRetention.next_monthly_cleanup_on}
                passSchedule={projectRetention}
                level="project"
                scope="Events in this project"
                owner="this project"
                note={
                    projectRetention.project_retention_months === null ? (
                        <>
                            <span>{`This project uses the organization's events retention. You can change it in `}</span>
                            <Link to={urls.settings('organization-details', 'organization-events-retention')}>
                                organization settings
                            </Link>
                            <span>.</span>
                        </>
                    ) : (
                        `This overrides the organization default of ${retentionPeriodLabel(defaultMonths)}.`
                    )
                }
                saving={projectRetentionLoading}
                restrictionReason={restrictionReason}
                onSave={updateProjectRetention}
                dataAttr="project-events-retention"
            />
        </div>
    )
}
