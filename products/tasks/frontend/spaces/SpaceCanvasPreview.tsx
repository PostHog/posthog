import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { Skeleton } from '@posthog/quill'

import { themeLogic } from 'lib/logic/themeLogic'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
import { BuiltCanvas } from 'products/canvas/frontend/host/BuiltCanvas'

import { spaceCanvasTemplateIcon } from './spaceCanvasDisplay'
import { spaceCanvasPreviewKey, spaceCanvasPreviewsLogic } from './spaceCanvasPreviewsLogic'

const NO_HIGHLIGHTS: never[] = []
const denyDataRequest = (): Promise<never> => Promise.reject(new Error('A canvas preview has no data access'))
const noUserActivation = (): boolean => false
const ignoreExternalOpen = (): void => {}

export function SpaceCanvasPreview({ spaceId, canvas }: { spaceId: string; canvas: CanvasApi }): JSX.Element {
    const previewKey = spaceCanvasPreviewKey(canvas)
    const logic = spaceCanvasPreviewsLogic({ spaceId })
    const { previews } = useValues(logic)
    const { requestPreview } = useActions(logic)
    const { isDarkModeOn } = useValues(themeLogic)
    const ref = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const element = ref.current
        if (!element || !previewKey) {
            return
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    requestPreview(previewKey, canvas.id)
                    observer.disconnect()
                }
            },
            { rootMargin: '400px 0px' }
        )
        observer.observe(element)
        return () => observer.disconnect()
    }, [previewKey, canvas.id, requestPreview])

    const preview = previewKey ? previews[previewKey] : null
    const TemplateIcon = spaceCanvasTemplateIcon(canvas.template_id)

    return (
        <div ref={ref} aria-hidden className="relative h-36 shrink-0 overflow-hidden border-b border-border bg-muted">
            {preview?.status === 'ready' && preview.artifactUrl ? (
                // Renders the canvas at four times the card's width, then scales it down to fit.
                <div
                    className="pointer-events-none absolute top-0 left-0 h-[400%] w-[400%] origin-top-left scale-25"
                    {...{ inert: '' }}
                >
                    <BuiltCanvas
                        artifactUrl={preview.artifactUrl}
                        capabilities={null}
                        theme={isDarkModeOn ? 'dark' : 'light'}
                        onDataRequest={denyDataRequest}
                        hasUserActivation={noUserActivation}
                        onOpenExternal={ignoreExternalOpen}
                        commentHighlights={NO_HIGHLIGHTS}
                        clearTextSelectionKey={0}
                    />
                </div>
            ) : previewKey && preview?.status !== 'unavailable' ? (
                <Skeleton className="size-full rounded-none" />
            ) : (
                <div className="flex size-full items-center justify-center">
                    <TemplateIcon className="size-6 text-muted-foreground" />
                </div>
            )}
        </div>
    )
}
