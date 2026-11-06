import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Slider } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'

export interface ComposerReasoningSliderProps {
    /** Stop keys in Faster → Smarter order. */
    stops: string[]
    currentStop?: string
    onSelect: (stop: string) => void
    onAdvanced: () => void
}

/**
 * The Faster/Smarter face of the model picker: an Advanced link above a notched slider whose stops the caller
 * defines. Mirrors the desktop app's `ReasoningSliderFace` so both surfaces read the same.
 */
export function ComposerReasoningSlider({
    stops,
    currentStop,
    onSelect,
    onAdvanced,
}: ComposerReasoningSliderProps): JSX.Element {
    const matchedIndex = stops.indexOf(currentStop ?? '')
    const activeIndex = matchedIndex >= 0 ? matchedIndex : Math.floor((stops.length - 1) / 2)
    // Continuous drag position so the thumb tracks the pointer fluidly; outside a drag the thumb derives from the
    // current selection, so releasing snaps it to the notch the live-applied selection landed on.
    const [dragPosition, setDragPosition] = useState<number | null>(null)
    const position = dragPosition ?? activeIndex
    const nearestIndex = Math.min(stops.length - 1, Math.max(0, Math.round(position)))

    const applyNotch = (notch: number): void => {
        const stop = stops[notch]
        if (stop && stop !== currentStop) {
            onSelect(stop)
        }
    }

    const nudge = (delta: number): void => {
        setDragPosition(null)
        applyNotch(Math.min(stops.length - 1, Math.max(0, nearestIndex + delta)))
    }

    return (
        <div className="flex min-w-[220px] flex-col gap-2 p-2">
            <button
                type="button"
                className="flex items-center gap-1 text-xs text-muted hover:text-default"
                onClick={onAdvanced}
            >
                Advanced
                <IconChevronRight className="text-xs" />
            </button>
            <div className="flex items-center justify-between gap-2 text-xs text-muted">
                <span>Faster ($)</span>
                <span>Smarter ($$$)</span>
            </div>
            <div
                className="relative py-1"
                onKeyDownCapture={(event) => {
                    if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
                        event.preventDefault()
                        event.stopPropagation()
                        nudge(-1)
                    } else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
                        event.preventDefault()
                        event.stopPropagation()
                        nudge(1)
                    }
                }}
            >
                <Slider
                    aria-label="Reasoning level"
                    min={0}
                    max={stops.length - 1}
                    step={0.01}
                    value={[position]}
                    onValueChange={(next: number | readonly number[]) => {
                        const raw = Array.isArray(next) ? next[0] : next
                        if (typeof raw !== 'number') {
                            return
                        }
                        setDragPosition(raw)
                        // Applied per notch crossing so the trigger pill tracks the drag.
                        applyNotch(Math.round(raw))
                    }}
                    onValueCommitted={(next: number | readonly number[]) => {
                        const raw = Array.isArray(next) ? next[0] : next
                        if (typeof raw === 'number') {
                            applyNotch(Math.min(stops.length - 1, Math.max(0, Math.round(raw))))
                        }
                        setDragPosition(null)
                    }}
                />
                <div className="-translate-y-1/2 pointer-events-none absolute inset-x-2 top-1/2 flex justify-between">
                    {stops.map((stop, stopIndex) => (
                        <span
                            key={stop}
                            className={cn(
                                'size-1 rounded-full',
                                stopIndex <= nearestIndex ? 'bg-(--background)/80' : 'bg-(--foreground)/30'
                            )}
                        />
                    ))}
                </div>
            </div>
        </div>
    )
}
