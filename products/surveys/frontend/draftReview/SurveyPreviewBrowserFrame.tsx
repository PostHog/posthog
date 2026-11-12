import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyPosition } from '~/types'

import type { SurveysSiteSnapshotRetrieveDevice } from 'products/surveys/frontend/generated/api.schemas'

import { SurveyPreviewArea } from './surveyReview'
import { surveySiteSnapshotLogic } from './surveySiteSnapshotLogic'

// The page is drawn at its real size and anchored to the survey's corner, so the frame crops the page around
// the survey instead of shrinking the page under a full-size survey.
const PLACEMENTS: Record<SurveyPosition, { survey: string; page: string }> = {
    [SurveyPosition.TopLeft]: { survey: 'top-4 left-4', page: 'top-0 left-0' },
    [SurveyPosition.TopCenter]: { survey: 'top-4 left-1/2 -translate-x-1/2', page: 'top-0 left-1/2 -translate-x-1/2' },
    [SurveyPosition.TopRight]: { survey: 'top-4 right-4', page: 'top-0 right-0' },
    [SurveyPosition.MiddleLeft]: { survey: 'top-1/2 left-4 -translate-y-1/2', page: 'top-1/2 left-0 -translate-y-1/2' },
    [SurveyPosition.MiddleCenter]: {
        survey: 'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2',
        page: 'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2',
    },
    [SurveyPosition.MiddleRight]: {
        survey: 'top-1/2 right-4 -translate-y-1/2',
        page: 'top-1/2 right-0 -translate-y-1/2',
    },
    [SurveyPosition.Left]: { survey: 'bottom-4 left-4', page: 'bottom-0 left-0' },
    [SurveyPosition.Center]: {
        survey: 'bottom-4 left-1/2 -translate-x-1/2',
        page: 'bottom-0 left-1/2 -translate-x-1/2',
    },
    [SurveyPosition.Right]: { survey: 'bottom-4 right-4', page: 'bottom-0 right-0' },
    [SurveyPosition.NextToTrigger]: { survey: 'bottom-4 right-4', page: 'bottom-0 right-0' },
}

const highlightClasses = (active: boolean): string =>
    cn(
        'outline-2 outline-offset-2 motion-safe:transition-[outline-color]',
        active ? 'outline-accent' : 'outline-transparent'
    )

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
    const placement = PLACEMENTS[survey.appearance?.position ?? SurveyPosition.Right]

    return (
        <div
            className={cn(
                'mx-auto flex min-h-0 w-full flex-1 flex-col overflow-hidden rounded border bg-surface-primary',
                isMobile && 'max-w-sm'
            )}
        >
            <div className="flex items-center gap-1.5 border-b bg-surface-secondary px-3 py-2" aria-hidden>
                {[0, 1, 2].map((dot) => (
                    <span key={dot} className="size-2.5 shrink-0 rounded-full bg-border" />
                ))}
                <span
                    className={cn(
                        'ml-2 min-w-0 flex-1 truncate rounded bg-surface-primary px-2 py-0.5 font-mono text-xs text-secondary',
                        pageHighlight
                    )}
                >
                    {readySnapshot?.pageUrl || survey.conditions?.url || 'Any page on your site'}
                </span>
            </div>
            <div className="relative flex min-h-[26rem] flex-1">
                {readySnapshot ? (
                    <div className={cn('absolute inset-1 overflow-hidden rounded', pageHighlight)} aria-hidden>
                        <img
                            src={readySnapshot.imageUrl}
                            alt=""
                            className={cn('absolute max-w-none', placement.page)}
                            style={{ width: readySnapshot.viewportWidth }}
                        />
                    </div>
                ) : (
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
                )}
                <div
                    className={cn(
                        'absolute flex max-h-[calc(100%-2rem)] max-w-[calc(100%-2rem)] flex-col rounded',
                        placement.survey,
                        highlightClasses(highlightedArea === 'survey')
                    )}
                >
                    {/* posthog-js hangs the close button half outside the survey card, so the scroll box pads for it */}
                    <div className="min-h-0 overflow-auto rounded pt-5 pr-5">{preview}</div>
                </div>
            </div>
        </div>
    )
}
