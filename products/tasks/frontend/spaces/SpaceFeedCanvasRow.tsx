import { Badge, Card, Text, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { shortTimeAgo } from '~/layout/today/todayWorkItems'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { spaceCanvasAuthor, spaceCanvasTemplateIcon } from './spaceCanvasDisplay'
import { TaskUserAvatar, taskUserName } from './TaskUserAvatar'

interface SpaceFeedCanvasRowProps {
    canvas: CanvasApi
    listRow: boolean
}

/** A canvas in the feed's Canvases view, as a card or a list row, like PostHog Desktop's. */
export function SpaceFeedCanvasRow({ canvas, listRow }: SpaceFeedCanvasRowProps): JSX.Element {
    const author = spaceCanvasAuthor(canvas)
    const TemplateIcon = spaceCanvasTemplateIcon(canvas.template_id)
    const icon = <TemplateIcon className="size-3.5 shrink-0 text-muted-foreground" />
    const age = shortTimeAgo(canvas.updated_at)
    const avatar = (
        <span role="img" aria-label={taskUserName(author)} className="relative flex shrink-0">
            <TaskUserAvatar user={author} />
        </span>
    )
    const name = (className: string): JSX.Element => (
        <LinkPrimitive
            to={urls.canvasDetail(canvas.id)}
            className={cn('min-w-0 truncate text-foreground after:absolute after:inset-0', className)}
            data-attr="today-space-feed-canvas-row"
        >
            {canvas.name || 'Untitled canvas'}
        </LinkPrimitive>
    )

    if (listRow) {
        return (
            <div className="relative flex h-8 w-full items-center gap-2 rounded-md px-2 transition-colors hover:bg-fill-selected has-focus-visible:ring-2 has-focus-visible:ring-ring">
                {icon}
                {name('flex-1 text-(length:--text-ui) leading-(--text-ui--line-height) font-medium')}
                {avatar}
                <Text render={<span />} size="xs" variant="muted" className="w-8 shrink-0 text-right" translate="no">
                    {age}
                </Text>
            </div>
        )
    }
    return (
        <Card
            size="sm"
            className="relative my-1.5 gap-0 rounded-xl px-4 pt-3.5 pb-3 transition-colors hover:bg-fill-hover has-focus-visible:ring-2 has-focus-visible:ring-ring"
        >
            <div className="flex min-w-0 items-center gap-3">
                <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
                    <span className="flex translate-y-0.5">{icon}</span>
                    {name('text-sm leading-snug font-semibold')}
                    <Text render={<span />} size="xs" variant="muted" className="shrink-0" translate="no">
                        {`· ${age}`}
                    </Text>
                </div>
                <Badge className="shrink-0">Canvas</Badge>
                {avatar}
            </div>
            {canvas.description && (
                <Text size="xs" variant="muted" className="mt-1 line-clamp-2 leading-normal break-words">
                    {canvas.description}
                </Text>
            )}
        </Card>
    )
}
