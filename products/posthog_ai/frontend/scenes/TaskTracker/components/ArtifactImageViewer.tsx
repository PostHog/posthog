import { PointerEvent, useCallback, useLayoutEffect, useRef, useState } from 'react'

import { IconMinus, IconPlus } from '@posthog/icons'
import { Button, Separator, Text, Toggle, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill-primitives'

const ZOOM_STEPS = [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8]
// Room the image keeps from the pane edges when it fits, so its border never touches them.
const FIT_INSET_PX = 48

type Zoom = 'fit' | number

function nextStep(current: number, direction: 1 | -1): number {
    const steps = direction === 1 ? ZOOM_STEPS : [...ZOOM_STEPS].reverse()
    return steps.find((step) => (direction === 1 ? step > current + 0.001 : step < current - 0.001)) ?? current
}

function ZoomButton({
    label,
    disabledReason,
    onClick,
    dataAttr,
    children,
}: {
    label: string
    disabledReason?: string
    onClick: () => void
    dataAttr: string
    children: JSX.Element
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        aria-label={label}
                        disabled={!!disabledReason}
                        onClick={onClick}
                        data-attr={dataAttr}
                    />
                }
            >
                {children}
            </TooltipTrigger>
            <TooltipContent>{disabledReason ?? label}</TooltipContent>
        </Tooltip>
    )
}

/** An image preview that fits the pane, zooms in steps, and pans by drag once it overflows. */
export function ArtifactImageViewer({ src, alt }: { src: string; alt: string }): JSX.Element {
    const paneRef = useRef<HTMLDivElement>(null)
    const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
    const [natural, setNatural] = useState<{ width: number; height: number } | null>(null)
    const [pane, setPane] = useState<{ width: number; height: number } | null>(null)
    const [zoom, setZoom] = useState<Zoom>('fit')
    const [dragging, setDragging] = useState(false)

    useLayoutEffect(() => {
        const element = paneRef.current
        if (!element) {
            return
        }
        const observer = new ResizeObserver(([entry]) =>
            setPane({ width: entry.contentRect.width, height: entry.contentRect.height })
        )
        observer.observe(element)
        return () => observer.disconnect()
    }, [])

    // A small image is shown at its own size, never stretched past 100%.
    const fitScale =
        natural && pane
            ? Math.min(1, (pane.width - FIT_INSET_PX) / natural.width, (pane.height - FIT_INSET_PX) / natural.height)
            : 1
    const scale = zoom === 'fit' ? fitScale : zoom
    const width = natural ? Math.max(1, Math.round(natural.width * scale)) : undefined
    const overflows = !!natural && !!pane && (width! > pane.width || natural.height * scale > pane.height)

    const zoomBy = useCallback((direction: 1 | -1) => setZoom(nextStep(scale, direction)), [scale])

    const onPointerDown = (event: PointerEvent<HTMLDivElement>): void => {
        const element = paneRef.current
        if (!overflows || !element || event.button !== 0) {
            return
        }
        dragRef.current = { x: event.clientX, y: event.clientY, left: element.scrollLeft, top: element.scrollTop }
        element.setPointerCapture(event.pointerId)
        setDragging(true)
    }
    const onPointerMove = (event: PointerEvent<HTMLDivElement>): void => {
        const element = paneRef.current
        const start = dragRef.current
        if (!element || !start) {
            return
        }
        element.scrollLeft = start.left - (event.clientX - start.x)
        element.scrollTop = start.top - (event.clientY - start.y)
    }
    const endDrag = (): void => {
        dragRef.current = null
        setDragging(false)
    }

    return (
        <div data-quill className="relative size-full">
            <div
                ref={paneRef}
                className={cn(
                    'size-full overflow-auto',
                    overflows && (dragging ? 'cursor-grabbing select-none' : 'cursor-grab')
                )}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
                onDoubleClick={() => setZoom(zoom === 'fit' ? 1 : 'fit')}
            >
                {/* min-size centers the image while it fits and lets the scroll area grow once it does not. */}
                <div className="flex min-h-full min-w-full w-max items-center justify-center p-6">
                    <img
                        src={src}
                        alt={alt}
                        draggable={false}
                        style={width ? { width } : undefined}
                        className={cn(
                            'block max-w-none rounded-sm border border-border bg-white',
                            !natural && 'invisible'
                        )}
                        onLoad={(event) =>
                            setNatural({
                                width: event.currentTarget.naturalWidth || 1,
                                height: event.currentTarget.naturalHeight || 1,
                            })
                        }
                    />
                </div>
            </div>
            {natural && (
                <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-0.5 rounded-md border border-border bg-background p-0.5 shadow-sm">
                    <ZoomButton
                        label="Zoom out"
                        disabledReason={scale <= ZOOM_STEPS[0] ? 'This is the smallest size' : undefined}
                        onClick={() => zoomBy(-1)}
                        dataAttr="task-artifact-zoom-out"
                    >
                        <IconMinus className="size-4" />
                    </ZoomButton>
                    <Text size="xs" render={<span />} className="w-11 text-center tabular-nums" aria-live="polite">
                        {`${Math.round(scale * 100)}%`}
                    </Text>
                    <ZoomButton
                        label="Zoom in"
                        disabledReason={
                            scale >= ZOOM_STEPS[ZOOM_STEPS.length - 1] ? 'This is the largest size' : undefined
                        }
                        onClick={() => zoomBy(1)}
                        dataAttr="task-artifact-zoom-in"
                    >
                        <IconPlus className="size-4" />
                    </ZoomButton>
                    <Separator orientation="vertical" className="mx-1 h-4" />
                    <Toggle
                        pressed={zoom === 'fit'}
                        onPressedChange={() => setZoom('fit')}
                        data-attr="task-artifact-zoom-fit"
                    >
                        Fit
                    </Toggle>
                    <Toggle
                        pressed={zoom === 1}
                        onPressedChange={() => setZoom(1)}
                        data-attr="task-artifact-zoom-actual"
                    >
                        100%
                    </Toggle>
                </div>
            )}
        </div>
    )
}
