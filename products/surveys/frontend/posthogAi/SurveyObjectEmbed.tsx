import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SurveyStatusTag } from 'scenes/surveys/components/SurveyStatusTag'
import { SurveyQuestionLabel } from 'scenes/surveys/constants'

import type { ObjectEmbedProps } from 'products/posthog_ai/frontend/api/types'

import { surveyObjectEmbedLogic } from './surveyObjectEmbedLogic'

function ResponseCount({ id }: { id: string }): JSX.Element {
    const { responseCount, responseCountLoading } = useValues(surveyObjectEmbedLogic({ id }))
    if (responseCount === null) {
        return responseCountLoading ? <LemonSkeleton className="h-4 w-24" /> : <span>Responses unavailable</span>
    }
    return (
        <span>
            {humanFriendlyNumber(responseCount)} {responseCount === 1 ? 'response' : 'responses'}
        </span>
    )
}

/** A read-only survey summary: status, response count and questions. */
export function SurveyObjectEmbed({ objectId }: ObjectEmbedProps): JSX.Element {
    const { survey, surveyMissing, questions } = useValues(surveyObjectEmbedLogic({ id: objectId }))
    if (surveyMissing) {
        return <NotFound object="survey" />
    }
    if (!survey) {
        return (
            <div className="flex flex-col gap-2 p-4">
                <LemonSkeleton className="h-6 w-48" />
                <LemonSkeleton className="h-32" />
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{survey.name}</span>
                    <SurveyStatusTag
                        survey={{ start_date: survey.start_date ?? null, end_date: survey.end_date ?? null }}
                    />
                    {survey.archived ? <LemonTag type="muted">Archived</LemonTag> : null}
                </div>
                {survey.description ? <p className="m-0 text-sm text-secondary">{survey.description}</p> : null}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-secondary">
                    <ResponseCount id={objectId} />
                    {survey.start_date ? (
                        <span>
                            Started <TZLabel time={survey.start_date} />
                        </span>
                    ) : null}
                    {survey.end_date ? (
                        <span>
                            Stopped <TZLabel time={survey.end_date} />
                        </span>
                    ) : null}
                </div>
            </div>
            <div className="flex flex-col gap-2">
                <span className="text-sm font-semibold">
                    {questions.length} {questions.length === 1 ? 'question' : 'questions'}
                </span>
                <ol className="m-0 flex list-none flex-col gap-2 p-0">
                    {questions.map((question, index) => (
                        <li
                            key={question.id ?? index}
                            className="flex flex-col gap-1 rounded-md border border-primary bg-surface-primary p-3"
                        >
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="text-xs text-secondary">{index + 1}.</span>
                                <span className="font-medium">{question.question}</span>
                                <LemonTag type="muted" size="small">
                                    {SurveyQuestionLabel[question.type]}
                                </LemonTag>
                            </div>
                            {'choices' in question && question.choices.length > 0 ? (
                                <div className="flex flex-wrap gap-1">
                                    {question.choices.map((choice) => (
                                        <LemonTag key={choice} size="small">
                                            {choice}
                                        </LemonTag>
                                    ))}
                                </div>
                            ) : null}
                        </li>
                    ))}
                </ol>
            </div>
        </div>
    )
}
