import { IconRefresh } from '@posthog/icons'
import { Badge, TableCell, TableRow, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SpaceLoop } from './spaceLoops'

export function SpaceLoopRow({ loop }: { loop: SpaceLoop }): JSX.Element {
    return (
        <TableRow>
            <TableCell expand>
                <div className="flex min-w-0 items-center gap-2">
                    <IconRefresh className="shrink-0 text-muted-foreground" aria-hidden />
                    <div className="flex min-w-0 flex-col gap-0.5">
                        <div className="flex min-w-0 items-center gap-2">
                            {/* Loop details live in PostHog Desktop, so the name opens the loop there. */}
                            <LinkPrimitive
                                to={urls.codeLoopLink(loop.id)}
                                target="_blank"
                                className="truncate font-medium text-foreground hover:underline"
                                data-attr="today-space-loop-open"
                            >
                                {loop.name || 'Untitled loop'}
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
            <TableCell className="hidden @lg:table-cell">
                <Text render={<span />} size="xs" className="truncate">
                    {loop.trigger}
                </Text>
            </TableCell>
            <TableCell className="hidden @md:table-cell">
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
        </TableRow>
    )
}
