import { Badge, Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { shortTimeAgo } from '~/layout/today/todayWorkItems'

import { SpaceLoopRun } from './spaceLoops'

export function SpaceLoopRunRow({ run }: { run: SpaceLoopRun }): JSX.Element {
    return (
        <Item
            variant="outline"
            size="sm"
            render={<LinkPrimitive to={urls.aiTask(run.taskId)} />}
            className="text-foreground transition-colors hover:bg-fill-hover hover:text-foreground"
            data-attr="today-space-loop-run"
        >
            <ItemContent className="min-w-0">
                <ItemTitle className="max-w-full">
                    <span className="min-w-0 truncate">{run.title ?? 'Loop run'}</span>
                </ItemTitle>
                <ItemDescription className={run.error ? 'text-destructive-foreground' : undefined}>
                    <span title={dayjs(run.startedAt).format('LLL')}>{shortTimeAgo(run.startedAt)}</span>
                    {run.error ? ` · ${run.error}` : ''}
                </ItemDescription>
            </ItemContent>
            {run.status && (
                <ItemActions>
                    <Badge variant={run.status.variant}>{run.status.label}</Badge>
                </ItemActions>
            )}
        </Item>
    )
}
