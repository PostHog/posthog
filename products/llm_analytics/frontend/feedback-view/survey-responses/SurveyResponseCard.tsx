import { Link } from '@posthog/lemon-ui'

import { isThumbQuestion } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { RatingSurveyQuestion, Survey, SurveyQuestion, SurveyQuestionType } from '~/types'

import { ChoiceResponse } from './ChoiceResponse'
import { OpenTextResponse } from './OpenTextResponse'
import { RatingScale } from './RatingScale'
import { ThumbsResponse } from './ThumbsResponse'
import { GroupedResponse } from './utils'

function QuestionResponse({ question, value }: { question: SurveyQuestion; value: unknown }): JSX.Element {
    if (isThumbQuestion(question)) {
        return <ThumbsResponse isPositive={value === '1'} question={question} />
    }

    if (question.type === SurveyQuestionType.Rating) {
        const numValue = typeof value === 'string' ? parseInt(value, 10) : Number(value)
        return <RatingScale value={numValue} question={question as RatingSurveyQuestion} />
    }

    if (question.type === SurveyQuestionType.SingleChoice || question.type === SurveyQuestionType.MultipleChoice) {
        return <ChoiceResponse value={value} question={question} />
    }

    return <OpenTextResponse value={value} question={question} />
}

export function SurveyResponseCard({ response, survey }: { response: GroupedResponse; survey: Survey }): JSX.Element {
    return (
        <div className="rounded-lg border border-border bg-bg-light p-3 flex flex-col gap-3">
            <Link
                to={urls.survey(survey.id)}
                className="self-start inline-flex items-center gap-1 text-xs font-medium text-link hover:underline"
                target="_blank"
                targetBlankIcon
            >
                {survey.name}
            </Link>

            {response.responses.map((r) => (
                <QuestionResponse key={r.questionIndex} question={r.question} value={r.value} />
            ))}

            {!response.isComplete && <span className="text-xs text-muted italic">Partial response</span>}
        </div>
    )
}
