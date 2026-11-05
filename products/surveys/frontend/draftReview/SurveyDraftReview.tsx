import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyInContextPreview } from './SurveyInContextPreview'
import { SurveyPreviewPageChips } from './SurveyPreviewPageChips'
import { SurveyReviewSectionKey, getSurveyDelivery, getSurveyReviewSections } from './surveyReview'
import { SurveyReviewSectionCard } from './SurveyReviewSectionCard'

export function SurveyDraftReview(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const [highlightedKey, setHighlightedKey] = useState<SurveyReviewSectionKey | null>(null)
    const sections = useMemo(() => getSurveyReviewSections(survey), [survey])
    const warningCount = sections.filter((section) => section.status === 'warning').length
    const readyCount = sections.length - warningCount
    const showsPageChips = getSurveyDelivery(survey) !== 'api'

    return (
        <div className="px-4 pb-4">
            <div className="mx-auto grid w-full max-w-[1200px] grid-cols-1 items-start gap-4 @min-[60rem]/main-content:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
                <div className="flex flex-col gap-3">
                    {sections.map((section) => (
                        <SurveyReviewSectionCard
                            key={section.key}
                            section={section}
                            highlighted={highlightedKey === section.key}
                            onHighlightChange={(highlighted) => setHighlightedKey(highlighted ? section.key : null)}
                        >
                            {section.key === 'questions' && showsPageChips && <SurveyPreviewPageChips />}
                        </SurveyReviewSectionCard>
                    ))}
                    <div className="sticky bottom-4 z-10 flex flex-wrap items-center gap-3 rounded border bg-surface-primary p-4 shadow-[var(--shadow-elevation-3000)]">
                        <div className="flex min-w-48 flex-1 flex-col gap-1">
                            <span className="font-semibold">Ready to launch</span>
                            <div className="flex flex-wrap gap-1">
                                <LemonTag type="success">{`${readyCount} ${readyCount === 1 ? 'looks' : 'look'} good`}</LemonTag>
                                {warningCount > 0 && <LemonTag type="warning">{`${warningCount} to check`}</LemonTag>}
                            </div>
                        </div>
                        <LaunchSurveyButton size="medium">Launch survey</LaunchSurveyButton>
                    </div>
                </div>
                <div className="order-first flex max-h-[calc(100vh-8rem)] min-h-0 flex-col @min-[60rem]/main-content:sticky @min-[60rem]/main-content:top-4 @min-[60rem]/main-content:order-none">
                    <SurveyInContextPreview
                        highlightedArea={
                            sections.find((section) => section.key === highlightedKey)?.previewArea ?? null
                        }
                    />
                </div>
            </div>
        </div>
    )
}
