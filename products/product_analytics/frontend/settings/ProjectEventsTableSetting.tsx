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

    const movedByPostHog = eventsTable.reads_new_events_table && eventsTable.use_new_events_table === null

    return (
        <div className="max-w-160">
            <p className="text-sm text-secondary mb-3">
                PostHog is going to start switching every project to the new events table on November 30. If you want to
                switch early, you can.{' '}
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
                    (eventsTable.can_choose ? null : "This project can't switch its events table yet.")
                }
                data-attr="project-events-table-switch"
            />
            {movedByPostHog ? (
                <p className="text-sm text-secondary mt-2">PostHog moved this project to the new table.</p>
            ) : null}
        </div>
    )
}
