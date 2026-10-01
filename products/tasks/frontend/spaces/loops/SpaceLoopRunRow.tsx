import { Badge, Button, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SpaceLoopRun } from './spaceLoops'

export function SpaceLoopRunRow({ run }: { run: SpaceLoopRun }): JSX.Element {
    return (
        <Button
            variant="outline"
            size="row"
            left
            render={<LinkPrimitive to={urls.aiTask(run.taskId)} />}
            className="h-auto min-w-0 gap-3 py-2"
            data-attr="today-space-loop-run"
        >
            <Badge variant={run.status.variant} className="shrink-0">
                {run.status.label}
            </Badge>
            <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate">{run.title ?? 'Loop run'}</span>
                {run.error && (
                    <Text render={<span />} size="xs" variant="destructive" className="truncate">
                        {run.error}
                    </Text>
                )}
            </span>
            <Text
                render={<span />}
                size="xs"
                variant="muted"
                className="shrink-0"
                title={dayjs(run.startedAt).format('LLL')}
            >
                {dayjs(run.startedAt).fromNow()}
            </Text>
        </Button>
    )
}
