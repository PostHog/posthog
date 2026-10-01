import { IconBrowser } from '@posthog/icons'
import { Badge, Card, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { shortTimeAgo } from '~/layout/today/todayWorkItems'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { TaskAvatarUser, TaskUserAvatar, taskUserName } from './TaskUserAvatar'

interface SpaceFeedCanvasRowProps {
    canvas: CanvasApi
    listRow: boolean
}

/** A canvas in the feed's Canvases view, as a card or a list row, like PostHog Desktop's. It does not open on the web yet. */
export function SpaceFeedCanvasRow({ canvas, listRow }: SpaceFeedCanvasRowProps): JSX.Element {
    const author: TaskAvatarUser = {
        uuid: canvas.created_by.uuid,
        email: canvas.created_by.email,
        first_name: canvas.created_by.first_name ?? '',
        last_name: canvas.created_by.last_name ?? '',
    }
    const icon = <IconBrowser className="size-3.5 shrink-0 text-muted-foreground" />
    const age = shortTimeAgo(canvas.updated_at)
    const avatar = (
        <span role="img" aria-label={taskUserName(author)} className="relative flex shrink-0">
            <TaskUserAvatar user={author} />
        </span>
    )
    // A disabled button keeps the canvas on the keyboard's path, and its overlay carries the tooltip across the row.
    const name = (className: string): JSX.Element => (
        <Tooltip>
            <TooltipTrigger
                render={
                    <button
                        type="button"
                        aria-disabled="true"
                        className={cn(
                            'min-w-0 cursor-default truncate text-left text-foreground after:absolute after:inset-0',
                            className
                        )}
                        data-attr="today-space-feed-canvas-row"
                    />
                }
            >
                {canvas.name || 'Untitled canvas'}
            </TooltipTrigger>
            <TooltipContent>Opens once canvases are on the web</TooltipContent>
        </Tooltip>
    )

    if (listRow) {
        return (
            <div className="relative flex h-8 w-full items-center gap-2 rounded-md px-2">
                {icon}
                {name('flex-1 text-sm font-medium')}
                {avatar}
                <Text render={<span />} size="xs" variant="muted" className="w-8 shrink-0 text-right" translate="no">
                    {age}
                </Text>
            </div>
        )
    }
    return (
        <Card size="sm" className="relative my-1.5 gap-0 rounded-xl px-4 pt-3.5 pb-3">
            <div className="flex min-w-0 items-center gap-3">
                <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
                    <span className="flex translate-y-0.5">{icon}</span>
                    {name('text-sm leading-snug font-semibold')}
                    <Text render={<span />} size="xs" variant="muted" className="shrink-0" translate="no">
                        {`· ${age}`}
                    </Text>
                </div>
                <Badge className="shrink-0">Canvas</Badge>
            </div>
            {canvas.description && (
                <Text size="xs" variant="muted" className="mt-1.5 line-clamp-2 leading-normal break-words">
                    {canvas.description}
                </Text>
            )}
            <div className="mt-3 flex justify-end">{avatar}</div>
        </Card>
    )
}
