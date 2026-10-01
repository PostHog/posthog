import { Card, ContextMenu, ContextMenuContent, ContextMenuTrigger, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { CONTEXT_PARTS } from '~/layout/today/todayMenuParts'
import { shortTimeAgo } from '~/layout/today/todayWorkItems'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { SpaceCanvasActions } from './SpaceCanvasActions'
import { spaceCanvasAuthor, spaceCanvasTemplateIcon } from './spaceCanvasDisplay'
import { SpaceCanvasMenu } from './SpaceCanvasMenu'
import { spaceCanvasUrl } from './spaceCanvasUrls'
import { TaskUserAvatar, taskUserName } from './TaskUserAvatar'

export function SpaceCanvasCard({ spaceId, canvas }: { spaceId: string; canvas: CanvasApi }): JSX.Element {
    const author = spaceCanvasAuthor(canvas)
    const authorName = taskUserName(author)
    const TemplateIcon = spaceCanvasTemplateIcon(canvas.template_id)
    return (
        <ContextMenu>
            <ContextMenuTrigger render={<div className="min-w-0" />}>
                <Card
                    size="sm"
                    className="group relative gap-1 rounded-xl px-4 py-3 transition-colors hover:bg-fill-hover"
                >
                    <div className="flex min-w-0 items-center gap-2">
                        <TemplateIcon className="size-3.5 shrink-0 text-muted-foreground" />
                        <LinkPrimitive
                            to={spaceCanvasUrl(canvas.id)}
                            className="min-w-0 flex-1 truncate text-sm font-medium text-foreground after:absolute after:inset-0"
                            data-attr="today-space-canvases-card"
                        >
                            {canvas.name || 'Untitled canvas'}
                        </LinkPrimitive>
                        <SpaceCanvasMenu spaceId={spaceId} canvas={canvas} />
                        <span aria-hidden className="relative flex shrink-0">
                            <TaskUserAvatar user={author} />
                        </span>
                    </div>
                    <Text size="xs" variant="muted" className="truncate">
                        {`Updated ${shortTimeAgo(canvas.updated_at)} · ${authorName}`}
                    </Text>
                </Card>
            </ContextMenuTrigger>
            <ContextMenuContent className="w-48">
                <SpaceCanvasActions
                    parts={CONTEXT_PARTS}
                    spaceId={spaceId}
                    canvas={canvas}
                    dataAttrPrefix="today-space-canvases-card-context"
                />
            </ContextMenuContent>
        </ContextMenu>
    )
}
