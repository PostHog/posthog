import { Card, ContextMenu, ContextMenuContent, ContextMenuTrigger, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { CONTEXT_PARTS } from '~/layout/today/todayMenuParts'
import { shortTimeAgo } from '~/layout/today/todayWorkItems'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { SpaceCanvasActions } from './SpaceCanvasActions'
import { spaceCanvasAuthor } from './spaceCanvasDisplay'
import { SpaceCanvasMenu } from './SpaceCanvasMenu'
import { SpaceCanvasPreview } from './SpaceCanvasPreview'
import { TaskUserAvatar, taskUserName } from './TaskUserAvatar'

export function SpaceCanvasCard({ spaceId, canvas }: { spaceId: string; canvas: CanvasApi }): JSX.Element {
    const author = spaceCanvasAuthor(canvas)
    const authorName = taskUserName(author)
    return (
        <ContextMenu>
            <ContextMenuTrigger render={<div className="min-w-0" />}>
                <Card
                    size="sm"
                    className="group relative gap-0 rounded-xl py-0 transition-colors hover:bg-fill-hover has-focus-visible:ring-2 has-focus-visible:ring-ring"
                >
                    <SpaceCanvasPreview spaceId={spaceId} canvas={canvas} />
                    <div className="flex min-w-0 flex-col gap-1 px-4 py-3">
                        <div className="flex min-w-0 items-center gap-2">
                            <LinkPrimitive
                                to={urls.canvasDetail(canvas.id)}
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
                    </div>
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
