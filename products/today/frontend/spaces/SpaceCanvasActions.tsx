import { useActions, useValues } from 'kea'

import { IconCopy, IconPin, IconPinFilled, IconTrash } from '@posthog/icons'

import { TodayMenuParts } from '~/layout/today/todayMenuParts'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { spaceSceneLogic } from './spaceSceneLogic'

interface SpaceCanvasActionsProps {
    parts: TodayMenuParts
    spaceId: string
    canvas: CanvasApi
    dataAttrPrefix: string
}

export function SpaceCanvasActions({
    parts: { Item },
    spaceId,
    canvas,
    dataAttrPrefix,
}: SpaceCanvasActionsProps): JSX.Element {
    const { pendingCanvasIds } = useValues(spaceSceneLogic({ id: spaceId }))
    const { copyCanvasLink, toggleCanvasPinned, setCanvasDeleteTarget } = useActions(spaceSceneLogic({ id: spaceId }))
    const attr = (name: string): string => `${dataAttrPrefix}-${name}`
    const pinned = !!canvas.pinned_at

    return (
        <>
            <Item onClick={() => copyCanvasLink(canvas)} dataAttr={attr('copy-link')}>
                <IconCopy />
                Copy link
            </Item>
            <Item
                onClick={() => toggleCanvasPinned(canvas.id)}
                disabled={pendingCanvasIds.includes(canvas.id)}
                dataAttr={attr('pin')}
            >
                {pinned ? <IconPinFilled /> : <IconPin />}
                <span>{pinned ? 'Unpin' : 'Pin'}</span>
            </Item>
            <Item onClick={() => setCanvasDeleteTarget(canvas)} variant="destructive" dataAttr={attr('delete')}>
                <IconTrash />
                Delete…
            </Item>
        </>
    )
}
