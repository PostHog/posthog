import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { eventsTableSettingLogic } from './eventsTableSettingLogic'

const EVENT_STORAGE_CHANGES_URL = 'https://posthog.com/blog/changing-event-storage'

export function ProjectEventsTableSetting(): JSX.Element | null {
    const { eventsTable, eventsTableLoading } = useValues(eventsTableSettingLogic)
    const { updateEventsTable } = useActions(eventsTableSettingLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!eventsTable) {
        return null
    }

    const movedByPostHog = eventsTable.reads_new_events_table && !eventsTable.can_choose

    return (
        <div className="max-w-160">
            <p className="text-sm text-secondary mb-3">
                {movedByPostHog
                    ? 'PostHog switched this project to the new events table.'
                    : 'PostHog is going to start switching every project to the new events table on November 30. If you want to switch early, you can.'}{' '}
                <Link to={EVENT_STORAGE_CHANGES_URL} target="_blank">
                    Read what changes
                </Link>
            </p>
            <LemonSwitch
                bordered
                checked={eventsTable.reads_new_events_table}
                onChange={updateEventsTable}
                label="Read events from the new table"
                loading={eventsTableLoading}
                disabledReason={
                    restrictionReason ??
                    (eventsTable.can_choose
                        ? null
                        : movedByPostHog
                          ? "PostHog switched this project, so it can't switch back."
                          : "This project can't switch its events table yet.")
                }
                data-attr="project-events-table-switch"
            />
        </div>
    )
}
