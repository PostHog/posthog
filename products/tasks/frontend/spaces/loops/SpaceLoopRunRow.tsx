import { IconBolt, IconGitBranch, IconPlay, IconClock, IconSpinner, IconWarning } from '@posthog/icons'
import { Badge, Button, Item, ItemActions, ItemContent, ItemTitle, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { shortTimeAgo } from '~/layout/today/todayWorkItems'

import { SpaceLoopRun } from './spaceLoopMapping'

/** How long a finished run took, or how long a running one has gone. Empty for a run that has not started. */
export function spaceLoopRunDuration(run: SpaceLoopRun, now = dayjs()): string {
    if (!run.completedAt && !run.stoppable) {
        return ''
    }
    const start = dayjs(run.startedAt)
    const end = run.completedAt ? dayjs(run.completedAt) : now
    // The API leaves a run's timestamps optional, so a run without them shows no duration.
    if (!start.isValid() || !end.isValid()) {
        return ''
    }
    const seconds = Math.max(0, end.diff(start, 'second'))
    if (seconds < 60) {
        return `${seconds}s`
    }
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) {
        return `${minutes}m ${seconds % 60}s`
    }
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function Meta({ icon, children, mono }: { icon: JSX.Element; children: string; mono?: boolean }): JSX.Element {
    return (
        <span className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
            <span className="flex size-3 shrink-0 items-center">{icon}</span>
            <span className={mono ? 'truncate font-mono' : 'truncate'}>{children}</span>
        </span>
    )
}

export function SpaceLoopRunRow({ run, onStop }: { run: SpaceLoopRun; onStop: () => void }): JSX.Element {
    const duration = spaceLoopRunDuration(run)
    return (
        <Item variant="outline" size="sm" className="relative transition-colors hover:bg-fill-hover">
            <ItemContent className="min-w-0 gap-1">
                <ItemTitle className="max-w-full">
                    {/* The link covers the row, so the whole row opens the run and the stop button stays its own target. */}
                    <LinkPrimitive
                        to={urls.aiTask(run.taskId)}
                        className="min-w-0 truncate text-foreground after:absolute after:inset-0"
                        data-attr="today-space-loop-run"
                    >
                        {run.title ?? 'Loop run'}
                    </LinkPrimitive>
                </ItemTitle>
                <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="text-xs text-muted-foreground" title={dayjs(run.startedAt).format('LLL')}>
                        {shortTimeAgo(run.startedAt)}
                    </span>
                    {run.branch && (
                        <Meta icon={<IconGitBranch />} mono>
                            {run.branch}
                        </Meta>
                    )}
                    {duration && <Meta icon={<IconClock />}>{duration}</Meta>}
                    {run.triggered !== null && (
                        <Meta icon={run.triggered ? <IconBolt /> : <IconPlay />}>
                            {run.triggered ? 'Triggered' : 'Manual'}
                        </Meta>
                    )}
                </span>
                {run.error && (
                    <span className="flex min-w-0 items-center gap-1">
                        <IconWarning className="size-3 shrink-0 text-destructive-foreground" />
                        <Text render={<span />} size="xs" variant="destructive" className="truncate">
                            {run.error}
                        </Text>
                    </span>
                )}
            </ItemContent>
            <ItemActions className="relative">
                {run.stoppable && (
                    <Button
                        size="sm"
                        variant="destructive-outline"
                        onClick={onStop}
                        data-attr="today-space-loop-run-stop"
                    >
                        Stop run
                    </Button>
                )}
                {run.status && (
                    <Badge variant={run.status.variant} className="gap-1">
                        {run.status.running && <IconSpinner className="size-3 motion-safe:animate-spin" />}
                        <span>{run.status.label}</span>
                    </Badge>
                )}
            </ItemActions>
        </Item>
    )
}
