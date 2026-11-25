import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { EventsRetentionPeriodSelect } from './EventsRetentionPeriodSelect'
import { EventsRetentionPlanNote } from './EventsRetentionPlanNote'
import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'
import { retentionPeriodLabel } from './retentionPeriodLabel'

export function ProjectEventsRetentionSetting(): JSX.Element | null {
    const { projectRetention, projectRetentionLoading } = useValues(eventsRetentionSettingsLogic)
    const { updateProjectRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!projectRetention) {
        return null
    }

    const organizationMonths =
        projectRetention.organization_retention_months === null
            ? null
            : Math.min(projectRetention.organization_retention_months, projectRetention.plan_retention_months)
    const defaultMonths = organizationMonths ?? projectRetention.default_retention_months

    const periodSelect = (
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
    )

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-160" />}>
                    Choose how long this project keeps events.{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={projectRetention.docs_url} target="_blank" />}
                    >
                        Learn more
                    </Button>
                </Text>
                <EventsRetentionPlanNote plan={projectRetention} />
                {periodSelect}
            </div>
        )
    }

    return (
        <div>
            <p className="max-w-160 text-sm text-secondary mb-2">
                Choose how long this project keeps events.{' '}
                <Link to={projectRetention.docs_url} target="_blank">
                    Learn more
                </Link>
            </p>
            <EventsRetentionPlanNote plan={projectRetention} />
            {periodSelect}
        </div>
    )
}
