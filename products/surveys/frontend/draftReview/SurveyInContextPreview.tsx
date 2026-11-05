import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getNextPreviewPageIndex } from 'scenes/surveys/surveyPreviewNavigation'
import { clampPreviewPageIndex } from 'scenes/surveys/utils'

import { SurveyPosition } from '~/types'

import { SurveyPreviewArea, getSurveyDelivery } from './surveyReview'

type PreviewDevice = 'desktop' | 'mobile'

const POSITION_CLASSES: Record<SurveyPosition, string> = {
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

const highlightClasses = (active: boolean): string =>
    cn(
        'outline-2 outline-offset-2 motion-safe:transition-[outline-color]',
        active ? 'outline-accent' : 'outline-transparent'
    )

export function SurveyInContextPreview({
    highlightedArea,
}: {
    highlightedArea: SurveyPreviewArea | null
}): JSX.Element {
    const { survey, selectedPageIndex } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)
    const [device, setDevice] = useState<PreviewDevice>('desktop')
    const delivery = getSurveyDelivery(survey)
    const pageIndex = clampPreviewPageIndex(selectedPageIndex, survey)
    // SurveyAppearancePreview re-renders the posthog-js survey whenever this callback changes identity,
    // and this component re-renders on every review section hover.
    const onPreviewSubmit = useCallback(
        (response: string | string[] | number | null): void => {
            const nextPageIndex = getNextPreviewPageIndex(survey, pageIndex, response)
            if (nextPageIndex !== null) {
                setSelectedPageIndex(nextPageIndex)
            }
        },
        [survey, pageIndex, setSelectedPageIndex]
    )

    if (delivery === 'api') {
        return (
            <p className="m-0 rounded border border-dashed p-4 text-sm text-secondary">
                API surveys have no preview. Your own code decides how the survey looks and where it shows.
            </p>
        )
    }

    const preview = (
        <SurveyAppearancePreview survey={survey} previewPageIndex={pageIndex} onPreviewSubmit={onPreviewSubmit} />
    )

    if (delivery === 'hosted') {
        return <div className="flex justify-center rounded border bg-surface-secondary p-4">{preview}</div>
    }

    const isMobile = device === 'mobile'

    return (
        <div className="flex min-h-0 flex-col gap-2">
            <div className="flex justify-end">
                <LemonSegmentedButton
                    size="xsmall"
                    value={device}
                    onChange={setDevice}
                    options={[
                        { value: 'desktop', label: 'Desktop', 'data-attr': 'survey-draft-review-preview-desktop' },
                        { value: 'mobile', label: 'Mobile', 'data-attr': 'survey-draft-review-preview-mobile' },
                    ]}
                />
            </div>
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
                            highlightClasses(highlightedArea === 'page')
                        )}
                    >
                        {survey.conditions?.url || 'Any page on your site'}
                    </span>
                </div>
                <div className="relative flex min-h-[26rem] flex-1">
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
                                highlightClasses(highlightedArea === 'page')
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
                    <div
                        className={cn(
                            'absolute rounded',
                            isMobile
                                ? 'inset-x-3 bottom-3'
                                : POSITION_CLASSES[survey.appearance?.position ?? SurveyPosition.Right],
                            highlightClasses(highlightedArea === 'survey')
                        )}
                    >
                        {preview}
                    </div>
                </div>
            </div>
        </div>
    )
}
