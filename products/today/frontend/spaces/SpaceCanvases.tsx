import { useActions, useValues } from 'kea'

import { IconPalette } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { SpaceCanvasCard } from './SpaceCanvasCard'
import { SpaceCanvasDeleteDialog } from './SpaceCanvasDeleteDialog'
import { spaceSceneLogic } from './spaceSceneLogic'

const GRID_CLASS = 'grid grid-cols-1 gap-3 @lg/main-content:grid-cols-2 @3xl/main-content:grid-cols-3'

function canvasGrid(spaceId: string, canvases: CanvasApi[]): JSX.Element {
    return (
        <div className={GRID_CLASS}>
            {canvases.map((canvas) => (
                <SpaceCanvasCard key={canvas.id} spaceId={spaceId} canvas={canvas} />
            ))}
        </div>
    )
}

function sectionLabel(label: string): JSX.Element {
    return (
        <Text render={<h3 />} size="xxs" variant="muted" className="mb-2 font-medium tracking-wider uppercase">
            {label}
        </Text>
    )
}

export function SpaceCanvases({ id }: { id: string }): JSX.Element {
    const { canvases, canvasesLoading, canvasesUnavailable, canvasSections } = useValues(spaceSceneLogic({ id }))
    const { loadCanvases } = useActions(spaceSceneLogic({ id }))

    if (canvasesUnavailable) {
        return (
            <Empty className="py-12">
                <EmptyHeader>
                    <EmptyTitle>Canvases didn’t load</EmptyTitle>
                    <EmptyDescription>Check your connection and try again.</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button
                        variant="outline"
                        loading={canvasesLoading}
                        onClick={() => loadCanvases()}
                        data-attr="today-space-canvases-retry"
                    >
                        Try again
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }
    if (canvases === null) {
        return (
            <div className="flex flex-col gap-3 pt-5" aria-busy>
                <Skeleton className="h-3.5 w-20" />
                <div className={GRID_CLASS}>
                    {Array.from({ length: 6 }, (_, index) => (
                        <Skeleton key={index} className="h-52 w-full rounded-xl" />
                    ))}
                </div>
            </div>
        )
    }
    if (canvases.length === 0) {
        return (
            <Empty className="py-12">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconPalette />
                    </EmptyMedia>
                    <EmptyTitle>No canvases yet</EmptyTitle>
                    <EmptyDescription>Ask your agent to make one with the PostHog MCP server.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    const { pinned, rest } = canvasSections
    return (
        <div className="flex flex-col pt-5">
            <Text size="xs" variant="muted" className="mb-3">
                {canvases.length === 1 ? '1 canvas' : `${canvases.length} canvases`}
            </Text>
            {pinned.length > 0 && (
                <>
                    {sectionLabel('Pinned')}
                    {canvasGrid(id, pinned)}
                    {rest.length > 0 && <div className="mt-5">{sectionLabel('All')}</div>}
                </>
            )}
            {rest.length > 0 && canvasGrid(id, rest)}
            <SpaceCanvasDeleteDialog spaceId={id} />
        </div>
    )
}
