import { useActions } from 'kea'

import { IconCalendar, IconChevronDown } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { releaseLogic } from './releaseLogic'
import { ReleaseScheduleFlagSearch } from './ReleaseScheduleFlagSearch'
import { ReleaseRow } from './releaseUtils'

const MENU_LIMIT = 10

export function ReleaseScheduleButton({
    row,
    variant = 'outline',
}: {
    row: ReleaseRow
    variant?: 'outline' | 'default'
}): JSX.Element | null {
    const { openSchedule } = useActions(releaseLogic)

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
        return <ReleaseScheduleFlagSearch row={row} />
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant={variant} data-attr="release-schedule" />}>
                <IconCalendar />
                Schedule a change
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {row.flags.map((flag) => (
                    <DropdownMenuItem
                        key={flag.id}
                        onClick={() => openSchedule(flag.id)}
                        data-attr="release-schedule-flag"
                    >
                        <span className="font-mono">{flag.key}</span>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
