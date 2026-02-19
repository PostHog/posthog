import { useValues } from 'kea'
import { renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useMemo, useRef } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'

import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { Survey, SurveyPosition, SurveyQuestionType, SurveyType } from '~/types'

function BrowserFrame({ children }: { children: React.ReactNode }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    return (
        <div className="rounded-lg border border-border bg-bg-light overflow-hidden">
            <div className="bg-fill-secondary px-3 py-2 border-b border-border flex items-center relative">
                <div className="flex gap-1.5 items-center">
                    <div className="size-3 rounded-full bg-[#ff5f57]" />
                    <div className="size-3 rounded-full bg-[#febc2e]" />
                    <div className="size-3 rounded-full bg-[#28c840]" />
                </div>
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                    <span className="text-xs font-medium text-muted">{currentTeam?.name || 'Your App'}</span>
                </div>
            </div>
            <div className="p-4 space-y-3">
                <div className="flex gap-3">
                    <UploadedLogo
                        name={currentOrganization?.name || 'Your App'}
                        entityId={currentOrganization?.id || '1'}
                        mediaId={currentOrganization?.logo_media_id || null}
                        size="medium"
                    />
                    {children}
                </div>
            </div>
        </div>
    )
}

export function FeedbackPreviewMock({
    thumbState,
    onThumbClick,
    followUpEnabled,
    followUpQuestion,
    surveyAppearance,
}: {
    thumbState: 'none' | 'up' | 'down'
    onThumbClick: (thumb: 'up' | 'down') => void
    followUpEnabled: boolean
    followUpQuestion: string
    surveyAppearance: Survey['appearance']
}): JSX.Element {
    const surveyPopupRef = useRef<HTMLDivElement>(null)

    const previewSurvey = useMemo(
        () => ({
            id: 'preview',
            name: 'Follow-up',
            type: SurveyType.API,
            questions: [
                {
                    type: SurveyQuestionType.Open,
                    question: followUpQuestion || 'What went wrong?',
                    optional: true,
                },
            ],
            appearance: {
                ...surveyAppearance,
                displayThankYouMessage: false,
                position: SurveyPosition.NextToTrigger,
            },
        }),
        [followUpQuestion, surveyAppearance]
    )

    useEffect(() => {
        if (surveyPopupRef.current && thumbState === 'down' && followUpEnabled) {
            renderSurveysPreview({
                survey: previewSurvey,
                parentElement: surveyPopupRef.current,
                previewPageIndex: 0,
                positionStyles: {
                    position: 'relative',
                    left: 'unset',
                    right: 'unset',
                    top: 'unset',
                    bottom: 'unset',
                    transform: 'unset',
                    maxWidth: '100%',
                    zIndex: '1',
                },
            })
        }
    }, [thumbState, followUpEnabled, previewSurvey])

    return (
        <BrowserFrame>
            <div className="flex-1 space-y-3">
                <div className="rounded-lg bg-fill-secondary p-3 text-sm">
                    You're absolutely right! Click the thumbs below to demo the user feedback flow.
                </div>

                <div className="flex items-center gap-2">
                    <span className="text-xs text-muted">Was this helpful?</span>
                    <div className="flex items-center gap-1">
                        <button
                            type="button"
                            onClick={() => onThumbClick('up')}
                            className={`p-1.5 rounded transition-colors ${
                                thumbState === 'up'
                                    ? 'bg-success-highlight text-success'
                                    : 'hover:bg-fill-secondary text-muted'
                            }`}
                        >
                            {thumbState === 'up' ? (
                                <IconThumbsUpFilled className="size-4" />
                            ) : (
                                <IconThumbsUp className="size-4" />
                            )}
                        </button>
                        <button
                            type="button"
                            onClick={() => onThumbClick('down')}
                            className={`p-1.5 rounded transition-colors ${
                                thumbState === 'down'
                                    ? 'bg-warning-highlight text-warning'
                                    : 'hover:bg-fill-secondary text-muted'
                            }`}
                        >
                            {thumbState === 'down' ? (
                                <IconThumbsDownFilled className="size-4" />
                            ) : (
                                <IconThumbsDown className="size-4" />
                            )}
                        </button>
                    </div>
                </div>

                {thumbState === 'down' && followUpEnabled && <div ref={surveyPopupRef} />}
            </div>
        </BrowserFrame>
    )
}
