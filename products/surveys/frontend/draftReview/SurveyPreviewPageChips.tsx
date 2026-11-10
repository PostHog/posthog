import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { clampPreviewPageIndex, getIntroScreenPageOptions } from 'scenes/surveys/utils'

export function SurveyPreviewPageChips(): JSX.Element {
    const { survey, selectedPageIndex } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)
    const currentPageIndex = clampPreviewPageIndex(selectedPageIndex, survey)

    const pages = [
        ...getIntroScreenPageOptions(survey),
        ...survey.questions.map((question, index) => ({
            label: `${index + 1}. ${question.question?.trim() || 'No text'}`,
            value: index,
        })),
        ...(survey.appearance?.displayThankYouMessage ? [{ label: 'Thank you', value: survey.questions.length }] : []),
    ]

    return (
        <div className="flex flex-wrap gap-1" role="group" aria-label="Preview page">
            {pages.map((page) => (
                <LemonButton
                    key={page.value}
                    type="secondary"
                    size="xsmall"
                    active={page.value === currentPageIndex}
                    aria-pressed={page.value === currentPageIndex}
                    onClick={() => setSelectedPageIndex(page.value)}
                    className="max-w-60"
                    truncate
                    data-attr="survey-draft-review-preview-page"
                >
                    {page.label}
                </LemonButton>
            ))}
        </div>
    )
}
