import { useRef } from 'react'

import { StepImportNotesList } from '../../../import/StepImportNotesList'
import type { HogFlowAction } from '../../types'
import { StepPreview } from './step-preview/StepPreview'
import { StepCountLine } from './StepCountLine'
import { StepFieldList } from './StepFieldList'
import type { StepPresentationKind } from './stepPresentation'
import { TILE_SIZE } from './tileCanvasLayout'
import { FIT_MARGIN } from './tileCanvasModel'
import { CAPTION_WIDTH, TileCaption } from './TileCaption'
import { TileFace } from './TileFace'
import { useKeepInView } from './useKeepInView'
import type { TileStep } from './useTileStep'

const PADDING = 14
const MIN_WIDTH = 440
const KIND_LABEL_ROOM = 72
const NAME_ROW_HEIGHT = 26
export const HOVER_CARD_CLOSE_MS = 200
// The border snaps to whole device pixels but the card's edge can fall between them, so a clip on the
// edge itself can shave the bottom border off. Clipping just outside the card keeps the whole border.
const OPEN_CLIP = 'inset(-2px round 18px)'
const PREVIEWS_THAT_SHOW_SETTINGS = new Set<StepPresentationKind>([
    'slack',
    'ai-task',
    'scout',
    'ticket-message',
    'ticket-update',
    'person',
    'webhook',
    'branch',
    'wait',
    'window',
])

/** The card starts clipped to the tile's own box, so the icon and caption stay put as it opens around them. */
export function TileHoverCard({
    open,
    action,
    tile,
    count,
    workflowId,
}: {
    open: boolean
    action: HogFlowAction
    tile: TileStep
    count: number | undefined
    workflowId: string
}): JSX.Element {
    const face = { width: TILE_SIZE, height: TILE_SIZE }
    const width = Math.max(MIN_WIDTH, face.width + 12 + CAPTION_WIDTH + PADDING * 2 + KIND_LABEL_ROOM)
    const nameRow = tile.customName ? NAME_ROW_HEIGHT : 0
    const faceTop = PADDING + nameRow
    const closedClip = `inset(${faceTop}px ${width - PADDING - face.width}px calc(100% - ${faceTop + face.height}px) ${PADDING}px round 12px)`
    const kind = tile.presentation.kind
    const showPreview = kind !== 'fields'
    const ref = useRef<HTMLDivElement>(null)
    const shift = useKeepInView(ref, open, FIT_MARGIN.bottom)
    return (
        <div
            ref={ref}
            className="absolute z-10 rounded-2xl border bg-surface-primary text-primary shadow-xl transition-[clip-path,transform] ease-[cubic-bezier(0.2,0.8,0.2,1)] motion-reduce:transition-none"
            style={{
                left: -PADDING,
                top: -faceTop,
                transform: `translate(${shift.x}px, ${shift.y}px)`,
                width,
                padding: PADDING,
                borderColor: tile.color,
                clipPath: open ? OPEN_CLIP : closedClip,
                transitionDuration: open ? '240ms' : `${HOVER_CARD_CLOSE_MS}ms`,
            }}
        >
            {tile.customName && (
                <div className="truncate text-[13px] font-semibold leading-tight" style={{ height: nameRow }}>
                    {tile.customName}
                </div>
            )}
            <div className="relative flex items-start gap-3">
                <TileFace tile={tile} count={count} />
                <TileCaption facts={tile.facts} size="card" />
                <div
                    className="absolute right-0 top-0 text-[10px] font-semibold uppercase tracking-wider"
                    style={{ color: tile.color }}
                >
                    {tile.label}
                </div>
            </div>
            <div
                className="mt-3 flex flex-col transition-opacity motion-reduce:transition-none"
                style={{
                    opacity: open ? 1 : 0,
                    transitionDuration: open ? '180ms' : '80ms',
                    transitionDelay: open ? '90ms' : '0ms',
                }}
            >
                {/* Each part returns null when it has nothing to show, so empty:hidden drops the section and its divider. */}
                <div className="flex flex-col gap-2.5 border-t py-3 empty:hidden">
                    {showPreview && <StepPreview action={action} tile={tile} />}
                    {(!showPreview || !PREVIEWS_THAT_SHOW_SETTINGS.has(kind)) && <StepFieldList facts={tile.facts} />}
                    <StepCountLine count={count} />
                </div>
                {workflowId && (
                    <div className="border-t py-3 empty:hidden">
                        <StepImportNotesList workflowId={workflowId} stepId={action.id} />
                    </div>
                )}
                <div className="border-t pt-2 text-[11px] text-secondary">Click to open the step</div>
            </div>
        </div>
    )
}
