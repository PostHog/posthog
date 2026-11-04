import { useReactFlow, useStore } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconChevronRight, IconCollapse, IconEllipsis, IconExpand } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { Box, PathFrameSpec, shortLabel } from './tileCanvasLayout'
import { tileCanvasLogic } from './tileCanvasLogic'
import { FIT_MARGIN, pathColor, Point } from './tileCanvasModel'

const TRAIL_ROOM = 56
const SHOWN_PATHS = 2
const PAN_MS = 300

interface TrailFrame {
    frame: PathFrameSpec
    box: Box
}

const contains = (box: Box, point: Point): boolean =>
    point.x >= box.x && point.x <= box.x + box.width && point.y >= box.y && point.y <= box.y + box.height

const framesAround = (framed: TrailFrame[], centre: Point): TrailFrame[] =>
    framed.filter(({ box }) => contains(box, centre)).sort((a, b) => a.frame.group.depth - b.frame.group.depth)

function framesOfStep(framed: TrailFrame[], stepId: string): TrailFrame[] {
    // A frame lists the steps drawn in it, so the step's own frame is the deepest that lists it, and its parents follow.
    const byId = new Map(framed.map((entry) => [entry.frame.id, entry]))
    let current = framed
        .filter(({ frame }) => frame.memberIds.includes(stepId))
        .reduce<TrailFrame | undefined>(
            (deepest, entry) => (!deepest || entry.frame.group.depth > deepest.frame.group.depth ? entry : deepest),
            undefined
        )
    const chain: TrailFrame[] = []
    while (current) {
        chain.unshift(current)
        current = current.frame.parentId ? byId.get(current.frame.parentId) : undefined
    }
    return chain
}

/** The open paths around the selected step, or around the middle of the view when no step is selected. */
function useTrail(): TrailFrame[] {
    const { frameSpecs, layout, selectedStepId } = useValues(tileCanvasLogic)
    const centreX = useStore((state) =>
        selectedStepId ? null : (state.width / 2 - state.transform[0]) / state.transform[2]
    )
    const centreY = useStore((state) =>
        selectedStepId ? null : (state.height / 2 - state.transform[1]) / state.transform[2]
    )
    const framed = useMemo(
        () =>
            frameSpecs.flatMap((frame) => {
                const box = layout?.frames[frame.id]
                return box ? [{ frame, box }] : []
            }),
        [frameSpecs, layout]
    )
    return useMemo(() => {
        if (selectedStepId) {
            return framesOfStep(framed, selectedStepId)
        }
        return centreX === null || centreY === null ? [] : framesAround(framed, { x: centreX, y: centreY })
    }, [framed, selectedStepId, centreX, centreY])
}

export function PathTrail(): JSX.Element | null {
    const { pathGroups, allPathsCollapsed, openPathIds } = useValues(tileCanvasLogic)
    const { setOpenPathIds, fitNextLayout, collapsePath, requestFit } = useActions(tileCanvasLogic)
    const { getViewport, setViewport } = useReactFlow()
    const canvasWidth = useStore((state) => state.width)
    const trail = useTrail()

    if (pathGroups.length === 0) {
        return null
    }

    const showPath = (box: Box): void => {
        const { zoom } = getViewport()
        void setViewport(
            {
                x: canvasWidth / 2 - (box.x + Math.min(box.width, canvasWidth / zoom) / 2) * zoom,
                y: FIT_MARGIN.top + TRAIL_ROOM - box.y * zoom,
                zoom,
            },
            { duration: PAN_MS }
        )
    }
    const innermost = trail[trail.length - 1]
    const hidden = trail.slice(0, Math.max(0, trail.length - SHOWN_PATHS))
    const shown = trail.slice(hidden.length)

    return (
        <div
            className="flex max-w-full flex-wrap items-center gap-2 rounded-lg border bg-surface-primary p-1 shadow-sm"
            data-attr="workflow-tile-path-trail"
        >
            <div className="flex items-center gap-1">
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconExpand />}
                    onClick={() => {
                        fitNextLayout()
                        setOpenPathIds(pathGroups.map((group) => group.id))
                    }}
                    disabledReason={
                        pathGroups.every((group) => openPathIds.includes(group.id)) ? 'Every path is open' : undefined
                    }
                    data-attr="workflow-tile-open-all-paths"
                >
                    Open all
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconCollapse />}
                    onClick={() => {
                        fitNextLayout()
                        setOpenPathIds([])
                    }}
                    disabledReason={allPathsCollapsed ? 'Every path is collapsed' : undefined}
                    data-attr="workflow-tile-collapse-all-paths"
                >
                    Collapse all
                </LemonButton>
            </div>
            {trail.length > 0 && (
                <nav aria-label="Open paths" className="flex min-w-0 flex-wrap items-center gap-0.5 text-xs">
                    <LemonButton size="xsmall" onClick={requestFit} tooltip="Back to the start of the workflow">
                        Start
                    </LemonButton>
                    {hidden.length > 0 && (
                        <span className="flex items-center gap-0.5">
                            <IconChevronRight className="size-3 shrink-0 text-tertiary" />
                            <LemonMenu
                                items={hidden.map(({ frame, box }) => ({
                                    label: shortLabel(frame.group.label),
                                    onClick: () => showPath(box),
                                }))}
                            >
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconEllipsis />}
                                    tooltip={`${hidden.length} more ${hidden.length === 1 ? 'path' : 'paths'} around this one`}
                                    aria-label="Show the paths around this one"
                                />
                            </LemonMenu>
                        </span>
                    )}
                    {shown.map(({ frame, box }) => {
                        const color = pathColor(frame.group.entryEdge)
                        return (
                            <span key={frame.id} className="flex min-w-0 items-center gap-0.5">
                                <IconChevronRight className="size-3 shrink-0 text-tertiary" />
                                <LemonButton
                                    size="xsmall"
                                    onClick={() => showPath(box)}
                                    tooltip={frame.group.label}
                                    data-attr="workflow-tile-path-trail-step"
                                >
                                    <span className="flex items-center gap-1">
                                        <span
                                            className="size-2 shrink-0 rounded-full"
                                            style={{ backgroundColor: color }}
                                        />
                                        <span style={{ color }}>{shortLabel(frame.group.label)}</span>
                                    </span>
                                </LemonButton>
                            </span>
                        )
                    })}
                    {innermost && (
                        <LemonButton
                            size="xsmall"
                            icon={<IconCollapse />}
                            onClick={() => collapsePath(innermost.frame.group.id)}
                            tooltip="Collapse this path"
                            aria-label="Collapse this path"
                        />
                    )}
                </nav>
            )}
        </div>
    )
}
