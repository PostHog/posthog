import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { EventsRetentionPeriodSelect } from './EventsRetentionPeriodSelect'
import { EventsRetentionPlanNote } from './EventsRetentionPlanNote'
import { eventsRetentionSettingsLogic } from './eventsRetentionSettingsLogic'

export function OrganizationEventsRetentionSetting(): JSX.Element | null {
    const { projectRetention, organizationRetention, organizationRetentionLoading } =
        useValues(eventsRetentionSettingsLogic)
    const { updateOrganizationRetention } = useActions(eventsRetentionSettingsLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!projectRetention || !organizationRetention) {
        return null
    }

    const periodSelect = (
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
    )

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-160" />}>
                    Choose how long projects in this organization keep events. A project can set its own period instead.{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={projectRetention.docs_url} target="_blank" />}
                    >
                        Learn more
                    </Button>
                </Text>
                <EventsRetentionPlanNote plan={organizationRetention} />
                {periodSelect}
            </div>
        )
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
            {periodSelect}
        </div>
    )
}
