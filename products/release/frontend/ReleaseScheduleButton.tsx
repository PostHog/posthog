import { useActions, useValues } from 'kea'

import { IconCalendar, IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { releaseLaunchLogic } from './releaseLaunchLogic'
import { releaseLogic } from './releaseLogic'
import { ReleaseScheduleFlagSearch } from './ReleaseScheduleFlagSearch'
import { ReleaseRow } from './releaseUtils'

const MENU_LIMIT = 10
const LAUNCH_LABEL = 'Launch all flags on one date'
const NO_EDIT_REASON = 'You need edit access to feature flags to schedule changes'

export function ReleaseScheduleButton({
    row,
    variant = 'outline',
}: {
    row: ReleaseRow
    variant?: 'outline' | 'default'
}): JSX.Element | null {
    const { canEditReleases } = useValues(releaseLogic)
    const { openSchedule } = useActions(releaseLogic)
    const { openLaunch } = useActions(releaseLaunchLogic)
    const launchAll = (): void =>
        openLaunch(row.flags.map((flag) => ({ id: flag.id, key: flag.key, active: !!flag.active })))

    if (!row.flags.length) {
        return null
    }
    if (row.flags.length === 1) {
        return (
            <Button variant={variant} data-attr="release-schedule" onClick={() => openSchedule(row.flags[0].id)}>
                <IconCalendar />
                Schedule a change
            </Button>
        )
    }
    if (row.flags.length > MENU_LIMIT) {
        return (
            <>
                <Button
                    variant={variant}
                    onClick={launchAll}
                    disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                    data-attr="release-launch-open"
                >
                    <IconCalendar />
                    {LAUNCH_LABEL}
                </Button>
                <ReleaseScheduleFlagSearch row={row} />
            </>
        )
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant={variant} data-attr="release-schedule" />}>
                <IconCalendar />
                Schedule a change
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem
                    onClick={launchAll}
                    disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                    data-attr="release-launch-open"
                >
                    {LAUNCH_LABEL}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                {row.flags.map((flag) => (
                    <DropdownMenuItem
                        key={flag.id}
                        onClick={() => openSchedule(flag.id)}
                        data-attr="release-schedule-flag"
                    >
                        <span>{flag.key}</span>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
