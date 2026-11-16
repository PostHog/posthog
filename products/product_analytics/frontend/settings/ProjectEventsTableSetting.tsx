import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { eventsTableSettingLogic } from './eventsTableSettingLogic'

const EVENT_STORAGE_CHANGES_URL = 'https://posthog.com/blog/changing-event-storage'

export function ProjectEventsTableSetting(): JSX.Element | null {
    const { eventsTable, eventsTableLoading, eventsTableLoadFailed } = useValues(eventsTableSettingLogic)
    const { loadEventsTable, updateEventsTable } = useActions(eventsTableSettingLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!eventsTable) {
        if (!eventsTableLoadFailed) {
            return <LemonSkeleton className="h-10 w-80" />
        }
        return (
            <div className="flex flex-wrap items-center gap-2 text-sm text-secondary">
                <span>Couldn't load this setting.</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={loadEventsTable}
                    loading={eventsTableLoading}
                    data-attr="project-events-table-retry"
                >
                    Try again
                </LemonButton>
            </div>
        )
    }

    const learnMore = (
        <Link to={EVENT_STORAGE_CHANGES_URL} target="_blank">
            Read what changes
        </Link>
    )

    if (eventsTable.reads_new_events_table && !eventsTable.can_choose) {
        return (
            <p className="max-w-160 text-sm text-secondary">
                PostHog switched this project to the new events table. {learnMore}
            </p>
        )
    }

    return (
        <div className="max-w-160">
            <p className="text-sm text-secondary mb-3">
                PostHog is going to start switching every project to the new events table on November 30. If you want to
                switch early, you can. {learnMore}
            </p>
            <LemonSwitch
                bordered
                checked={eventsTable.reads_new_events_table}
                onChange={updateEventsTable}
                label="Read events from the new table"
                loading={eventsTableLoading}
                disabledReason={
                    restrictionReason ??
                    (eventsTable.can_choose ? null : "This project can't switch its events table yet.")
                }
                data-attr="project-events-table-switch"
            />
        </div>
    )
}
