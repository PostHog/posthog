import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

const EVENT_STORAGE_CHANGES_URL = 'https://posthog.com/blog/changing-event-storage'

export function ProjectEventsTableSetting(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const blogLink = (text: string): JSX.Element => (
        <Link to={EVENT_STORAGE_CHANGES_URL} target="_blank">
            {text}
        </Link>
    )

    // default_modifiers holds the table PostHog put the project on, and modifiers the project's own early opt-in.
    if (currentTeam?.default_modifiers?.useNewEventsSchema) {
        return (
            <p className="max-w-160 text-sm text-secondary">
                PostHog switched this project to the new events table. {blogLink('Read what changed')}
            </p>
        )
    }

    return (
        <div className="max-w-160">
            <p className="text-sm text-secondary mb-3">
                PostHog is going to start switching every project to the new events table on November 30. If you want to
                switch early, you can. {blogLink('Read what changes')}
            </p>
            <LemonSwitch
                bordered
                checked={!!currentTeam?.modifiers?.useNewEventsSchema}
                onChange={(checked) =>
                    updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, useNewEventsSchema: checked } })
                }
                label="Read events from the new table"
                loading={currentTeamLoading}
                disabledReason={restrictedReason}
                data-attr="project-events-table-switch"
            />
        </div>
    )
}
