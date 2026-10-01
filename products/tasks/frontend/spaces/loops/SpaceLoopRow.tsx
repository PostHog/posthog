import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Badge, Switch, TableCell, TableRow, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SpaceLoop } from './spaceLoops'
import { spaceLoopsLogic } from './spaceLoopsLogic'

export function SpaceLoopRow({ spaceId, loop }: { spaceId: string; loop: SpaceLoop }): JSX.Element {
    const { pendingLoopIds } = useValues(spaceLoopsLogic({ id: spaceId }))
    const { setLoopEnabled } = useActions(spaceLoopsLogic({ id: spaceId }))
    const name = loop.name || 'Untitled loop'

    return (
        <TableRow className={loop.enabled ? undefined : 'opacity-70'}>
            <TableCell expand>
                <div className="flex min-w-0 items-center gap-2">
                    <IconRefresh className="shrink-0 text-muted-foreground" aria-hidden />
                    <div className="flex min-w-0 flex-col gap-0.5">
                        <div className="flex min-w-0 items-center gap-2">
                            <LinkPrimitive
                                to={urls.taskSpaceLoop(spaceId, loop.id)}
                                className="truncate font-medium text-foreground hover:underline"
                                data-attr="today-space-loop-open"
                            >
                                {name}
                            </LinkPrimitive>
                            <Badge variant={loop.status.variant} className="shrink-0">
                                {loop.status.label}
                            </Badge>
                        </div>
                        {loop.description && (
                            <Text render={<span />} size="xs" variant="muted" className="truncate">
                                {loop.description}
                            </Text>
                        )}
                    </div>
                </div>
            </TableCell>
            <TableCell className="hidden @2xl:table-cell">
                <Text render={<span />} size="xs" className="truncate">
                    {loop.trigger}
                </Text>
            </TableCell>
            <TableCell className="hidden @xl:table-cell">
                {loop.lastRunAt ? (
                    <Text
                        render={<span />}
                        size="xs"
                        variant={loop.lastRunFailed ? 'destructive' : 'default'}
                        title={dayjs(loop.lastRunAt).format('LLL')}
                    >
                        {loop.lastRunFailed
                            ? `Failed ${dayjs(loop.lastRunAt).fromNow()}`
                            : dayjs(loop.lastRunAt).fromNow()}
                    </Text>
                ) : (
                    <Text render={<span />} size="xs" variant="muted">
                        Never ran
                    </Text>
                )}
            </TableCell>
            <TableCell>
                <Switch
                    size="sm"
                    checked={loop.enabled}
                    disabled={pendingLoopIds.includes(loop.id)}
                    onCheckedChange={(checked: boolean) => setLoopEnabled(loop.id, checked)}
                    aria-label={loop.enabled ? `Pause ${name}` : `Resume ${name}`}
                    data-attr="today-space-loop-enabled"
                />
            </TableCell>
        </TableRow>
    )
}
