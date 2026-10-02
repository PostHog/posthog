import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import {
    Badge,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Switch,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { formatScheduleTime } from './form/loopSchedule'
import { SpaceLoop, spaceLoopName } from './spaceLoopMapping'
import { spaceLoopsLogic } from './spaceLoopsLogic'

function lastRunText(loop: SpaceLoop): string {
    if (!loop.lastRunAt) {
        return 'Never ran'
    }
    const age = dayjs(loop.lastRunAt).fromNow()
    return loop.lastRunFailed ? `Last run failed ${age}` : `Last run ${age}`
}

export function SpaceLoopRow({ spaceId, loop }: { spaceId: string; loop: SpaceLoop }): JSX.Element {
    const { pendingLoopIds } = useValues(spaceLoopsLogic({ id: spaceId }))
    const { setLoopEnabled } = useActions(spaceLoopsLogic({ id: spaceId }))
    const name = spaceLoopName(loop)

    return (
        <Item variant="outline" size="sm" className="relative" data-attr="today-space-loop-row">
            <ItemMedia variant="icon" className="text-muted-foreground">
                <IconRefresh />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="max-w-full">
                    {/* The link covers the row, so the whole row opens the loop and the switch stays its own target. */}
                    <LinkPrimitive
                        to={urls.taskSpaceLoop(spaceId, loop.id)}
                        className="min-w-0 truncate text-foreground after:absolute after:inset-0 hover:underline"
                        data-attr="today-space-loop-open"
                    >
                        {name}
                    </LinkPrimitive>
                    {/* Above the row link, so the paused reason shows on hover. */}
                    <Tooltip disabled={!loop.pausedReason}>
                        <TooltipTrigger render={<span className="relative flex shrink-0" />}>
                            <Badge variant={loop.status.variant}>{loop.status.label}</Badge>
                        </TooltipTrigger>
                        <TooltipContent>{loop.pausedReason}</TooltipContent>
                    </Tooltip>
                    {loop.visibility === 'personal' && <Badge className="shrink-0">Personal</Badge>}
                </ItemTitle>
                <ItemDescription className={loop.lastRunFailed ? 'text-destructive-foreground' : undefined}>
                    {[
                        loop.description,
                        loop.trigger,
                        loop.nextRunAt
                            ? `Next run ${formatScheduleTime(new Date(loop.nextRunAt), loop.nextRunTimezone)}`
                            : null,
                        lastRunText(loop),
                    ]
                        .filter(Boolean)
                        .join(' · ')}
                </ItemDescription>
            </ItemContent>
            <ItemActions className="relative">
                <Switch
                    size="sm"
                    checked={loop.enabled}
                    disabled={pendingLoopIds.includes(loop.id)}
                    onCheckedChange={(checked: boolean) => setLoopEnabled(loop.id, checked)}
                    aria-label={loop.enabled ? `Pause ${name}` : `Resume ${name}`}
                    data-attr="today-space-loop-enabled"
                />
            </ItemActions>
        </Item>
    )
}
