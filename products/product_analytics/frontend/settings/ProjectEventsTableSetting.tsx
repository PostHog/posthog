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
            <p className="text-sm text-secondary mb-2">
                PostHog is moving every project to a new events table. You can switch this project now, and switch back
                if something looks wrong.{' '}
                <Link to={EVENT_STORAGE_CHANGES_URL} target="_blank">
                    Learn more
                </Link>
            </p>
            <p className="text-sm text-secondary mb-1">On the new table:</p>
            <ul className="list-disc pl-5 text-sm text-secondary mb-3">
                <li>
                    Feature flag call events go back about 90 days, and counts of all events no longer include them.
                </li>
                <li>
                    Events keep <code>$set</code> and <code>$set_once</code> for 60 days.
                </li>
                <li>
                    Whole events leave out null values and empty objects, and store a few built-in properties as text.
                </li>
            </ul>
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
