import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { Button, Field, FieldLabel, Switch, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'

const EVENT_STORAGE_CHANGES_URL = 'https://posthog.com/blog/changing-event-storage'

export function ProjectEventsTableSetting(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const switchId = useId()

    const blogLink = (text: string): JSX.Element =>
        todayRailNav ? (
            <Button
                variant="link"
                size="inline"
                nativeButton={false}
                render={<LinkPrimitive to={EVENT_STORAGE_CHANGES_URL} target="_blank" />}
            >
                {text}
            </Button>
        ) : (
            <Link to={EVENT_STORAGE_CHANGES_URL} target="_blank">
                {text}
            </Link>
        )

    const handleChange = (checked: boolean): void =>
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, useNewEventsSchema: checked } })

    // default_modifiers holds the table PostHog put the project on, and modifiers the project's own early opt-in.
    if (currentTeam?.default_modifiers?.useNewEventsSchema) {
        if (todayRailNav) {
            return (
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-160" />}>
                    PostHog switched this project to the new events table. {blogLink('Read what changed')}
                </Text>
            )
        }

        return (
            <p className="max-w-160 text-sm text-secondary">
                PostHog switched this project to the new events table. {blogLink('Read what changed')}
            </p>
        )
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2 max-w-160">
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    PostHog is going to start switching every project to the new events table on November 30. If you
                    want to switch early, you can. {blogLink('Read what changes')}
                </Text>
                <Field orientation="horizontal" className="w-fit">
                    <Switch
                        id={switchId}
                        checked={!!currentTeam?.modifiers?.useNewEventsSchema}
                        onCheckedChange={handleChange}
                        disabled={currentTeamLoading}
                        disabledReason={restrictedReason}
                        data-attr="project-events-table-switch"
                    />
                    <FieldLabel htmlFor={switchId}>Read events from the new table</FieldLabel>
                </Field>
            </div>
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
                onChange={handleChange}
                label="Read events from the new table"
                loading={currentTeamLoading}
                disabledReason={restrictedReason}
                data-attr="project-events-table-switch"
            />
        </div>
    )
}
