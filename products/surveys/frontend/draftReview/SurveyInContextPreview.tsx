import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getNextPreviewPageIndex } from 'scenes/surveys/surveyPreviewNavigation'
import { clampPreviewPageIndex, getFirstPreviewPageIndex } from 'scenes/surveys/utils'

import type { SurveysSiteSnapshotRetrieveDevice } from 'products/surveys/frontend/generated/api.schemas'

import { SurveyPreviewBrowserFrame } from './SurveyPreviewBrowserFrame'
import { SurveyPreviewArea, getSurveyDelivery } from './surveyReview'

export function SurveyInContextPreview({
    highlightedArea,
}: {
    highlightedArea: SurveyPreviewArea | null
}): JSX.Element {
    const { survey, selectedPageIndex } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)
    const [device, setDevice] = useState<SurveysSiteSnapshotRetrieveDevice>('desktop')
    const delivery = getSurveyDelivery(survey)
    const pageIndex = clampPreviewPageIndex(selectedPageIndex, survey)
    // SurveyAppearancePreview re-renders the posthog-js survey whenever a callback changes identity,
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
    const onPreviewBack = useCallback(
        (): void => setSelectedPageIndex(Math.max(getFirstPreviewPageIndex(survey), pageIndex - 1)),
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
        <SurveyAppearancePreview
            survey={survey}
            previewPageIndex={pageIndex}
            onPreviewSubmit={onPreviewSubmit}
            onPreviewBack={onPreviewBack}
        />
    )

    if (delivery === 'hosted') {
        return <div className="flex justify-center rounded border bg-surface-secondary p-4">{preview}</div>
    }

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
            <SurveyPreviewBrowserFrame device={device} highlightedArea={highlightedArea} preview={preview} />
        </div>
    )
}
