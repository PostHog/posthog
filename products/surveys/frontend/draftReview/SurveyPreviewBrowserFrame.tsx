import { useValues } from 'kea'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { cn } from 'lib/utils/css-classes'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyPosition } from '~/types'

import type { SurveysSiteSnapshotRetrieveDevice } from 'products/surveys/frontend/generated/api.schemas'

import { SurveyPreviewZoomControls } from './SurveyPreviewZoomControls'
import { SurveyPreviewArea } from './surveyReview'
import { surveySiteSnapshotLogic } from './surveySiteSnapshotLogic'

const SURVEY_PLACEMENTS: Record<SurveyPosition, string> = {
    [SurveyPosition.TopLeft]: 'top-4 left-4',
    [SurveyPosition.TopCenter]: 'top-4 left-1/2 -translate-x-1/2',
    [SurveyPosition.TopRight]: 'top-4 right-4',
    [SurveyPosition.MiddleLeft]: 'top-1/2 left-4 -translate-y-1/2',
    [SurveyPosition.MiddleCenter]: 'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2',
    [SurveyPosition.MiddleRight]: 'top-1/2 right-4 -translate-y-1/2',
    [SurveyPosition.Left]: 'bottom-4 left-4',
    [SurveyPosition.Center]: 'bottom-4 left-1/2 -translate-x-1/2',
    [SurveyPosition.Right]: 'bottom-4 right-4',
    [SurveyPosition.NextToTrigger]: 'bottom-4 right-4',
}

const MAX_SCALE = 2
const WHEEL_ZOOM_SENSITIVITY = 0.01
// A mouse wheel notch reports a delta near 100 where a pinch reports a few, so one notch is capped near one button step.
const MAX_WHEEL_DELTA = 25

const highlightClasses = (active: boolean): string =>
    cn(
        'outline-2 outline-offset-2 motion-safe:transition-[outline-color]',
        active ? 'outline-accent' : 'outline-transparent'
    )

function centerOn(viewport: HTMLElement, element: HTMLElement): void {
    const viewportRect = viewport.getBoundingClientRect()
    const elementRect = element.getBoundingClientRect()
    viewport.scrollLeft += elementRect.left + elementRect.width / 2 - (viewportRect.left + viewportRect.width / 2)
    viewport.scrollTop += elementRect.top + elementRect.height / 2 - (viewportRect.top + viewportRect.height / 2)
}

export function SurveyPreviewBrowserFrame({
    device,
    highlightedArea,
    preview,
}: {
    device: SurveysSiteSnapshotRetrieveDevice
    highlightedArea: SurveyPreviewArea | null
    preview: ReactNode
}): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const urlCondition = `${survey.conditions?.urlMatchType ?? ''}:${survey.conditions?.url ?? ''}`
    const { readySnapshot } = useValues(surveySiteSnapshotLogic({ surveyId: survey.id, device, urlCondition }))
    const isMobile = device === 'mobile'
    const pageHighlight = highlightClasses(highlightedArea === 'page')
    const surveyPlacement = SURVEY_PLACEMENTS[survey.appearance?.position ?? SurveyPosition.Right]

    // The viewport mounts only once the snapshot is ready, so the resize observer follows the element, not a ref.
    const [viewport, setViewport] = useState<HTMLDivElement | null>(null)
    const surveyRef = useRef<HTMLDivElement>(null)
    const { width: viewportWidth = 0, height: viewportHeight = 0 } = useResizeObserver({ ref: viewport })
    const [pageHeight, setPageHeight] = useState<number | null>(null)
    const [zoom, setZoom] = useState<number | 'fit'>('fit')

    const pageWidth = readySnapshot?.viewportWidth ?? 0
    const fitScale =
        pageWidth && pageHeight && viewportWidth
            ? Math.min(viewportWidth / pageWidth, viewportHeight / pageHeight, 1)
            : null
    const scale = fitScale === null ? null : zoom === 'fit' ? fitScale : zoom

    const zoomTo = (next: number | 'fit'): void => {
        if (next === 'fit' || fitScale === null) {
            setZoom('fit')
            return
        }
        const clamped = Math.min(MAX_SCALE, Math.max(fitScale, next))
        setZoom(clamped === fitScale ? 'fit' : clamped)
    }

    useLayoutEffect(() => {
        if (viewport && surveyRef.current) {
            centerOn(viewport, surveyRef.current)
        }
    }, [viewport, scale])

    // A trackpad pinch arrives as a wheel event with ctrlKey, and only a non-passive listener can stop the page zooming.
    useEffect(() => {
        if (!viewport || scale === null) {
            return
        }
        const onWheel = (event: WheelEvent): void => {
            if (!event.ctrlKey) {
                return
            }
            event.preventDefault()
            const delta = Math.max(-MAX_WHEEL_DELTA, Math.min(MAX_WHEEL_DELTA, event.deltaY))
            zoomTo(scale * Math.exp(-delta * WHEEL_ZOOM_SENSITIVITY))
        }
        viewport.addEventListener('wheel', onWheel, { passive: false })
        return () => viewport.removeEventListener('wheel', onWheel)
    })

    const surveyLayer = (
        <div
            ref={surveyRef}
            className={cn(
                'absolute flex max-h-[calc(100%-2rem)] max-w-[calc(100%-2rem)] flex-col rounded',
                surveyPlacement,
                highlightClasses(highlightedArea === 'survey')
            )}
        >
            {/* posthog-js hangs the close button half outside the survey card, so the scroll box pads for it */}
            <div className="min-h-0 overflow-auto rounded pt-5 pr-5">{preview}</div>
        </div>
    )

    return (
        <div
            className={cn(
                'mx-auto flex min-h-0 w-full flex-1 flex-col overflow-hidden rounded border bg-surface-primary',
                isMobile && 'max-w-sm'
            )}
        >
            <div className="flex items-center gap-1.5 border-b bg-surface-secondary px-3 py-2">
                {[0, 1, 2].map((dot) => (
                    <span key={dot} className="size-2.5 shrink-0 rounded-full bg-border" aria-hidden />
                ))}
                <span
                    className={cn(
                        'ml-2 min-w-0 flex-1 truncate rounded bg-surface-primary px-2 py-0.5 font-mono text-xs text-secondary',
                        pageHighlight
                    )}
                >
                    {readySnapshot?.pageUrl || survey.conditions?.url || 'Any page on your site'}
                </span>
                {readySnapshot && scale !== null && fitScale !== null && (
                    <SurveyPreviewZoomControls scale={scale} fitScale={fitScale} maxScale={MAX_SCALE} onZoom={zoomTo} />
                )}
            </div>
            <div className="relative flex min-h-[26rem] flex-1">
                {readySnapshot ? (
                    <div ref={setViewport} className={cn('absolute inset-1 flex overflow-auto rounded', pageHighlight)}>
                        <div
                            className={cn('relative m-auto shrink-0', scale === null && 'invisible')}
                            style={{ width: pageWidth * (scale ?? 1), height: (pageHeight ?? 0) * (scale ?? 1) }}
                        >
                            <div
                                className="absolute top-0 left-0 origin-top-left"
                                style={{ width: pageWidth, transform: `scale(${scale ?? 1})` }}
                            >
                                <img
                                    src={readySnapshot.imageUrl}
                                    alt=""
                                    aria-hidden
                                    className="block w-full max-w-none"
                                    onLoad={(event) =>
                                        setPageHeight(
                                            (pageWidth * event.currentTarget.naturalHeight) /
                                                event.currentTarget.naturalWidth
                                        )
                                    }
                                />
                                {surveyLayer}
                            </div>
                        </div>
                    </div>
                ) : (
                    <>
                        <div className="flex w-full" aria-hidden>
                            {!isMobile && (
                                <div className="flex w-36 shrink-0 flex-col gap-2 border-r p-3">
                                    {[0, 1, 2, 3, 4, 5].map((bar) => (
                                        <span key={bar} className="h-2.5 rounded-sm bg-border" />
                                    ))}
                                </div>
                            )}
                            <div
                                className={cn(
                                    'm-6 flex flex-1 flex-col items-center gap-3 self-center rounded p-4',
                                    pageHighlight
                                )}
                            >
                                <span className="h-4 w-1/2 rounded-sm bg-border" />
                                <span className="h-10 w-full max-w-md rounded border bg-surface-secondary" />
                                <div className="flex flex-wrap justify-center gap-2">
                                    {[0, 1, 2].map((chip) => (
                                        <span key={chip} className="h-5 w-20 rounded-full border" />
                                    ))}
                                </div>
                            </div>
                        </div>
                        {surveyLayer}
                    </>
                )}
            </div>
        </div>
    )
}
