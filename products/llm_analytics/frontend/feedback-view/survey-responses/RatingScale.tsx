import { SURVEY_RATING_SCALE } from 'scenes/surveys/constants'

import { RatingSurveyQuestion } from '~/types'

export function RatingScale({ value, question }: { value: number; question: RatingSurveyQuestion }): JSX.Element {
    const { scale } = question
    const isNps = scale === SURVEY_RATING_SCALE.NPS_10_POINT
    const start = isNps ? 0 : 1
    const points = Array.from({ length: scale }, (_, i) => start + i)

    return (
        <div className="flex flex-col gap-1.5">
            {question.question && <span className="text-xs text-muted">{question.question}</span>}
            <div className="flex items-center gap-1">
                {points.map((point) => {
                    const isSelected = point === value
                    return (
                        <span
                            key={point}
                            className={`inline-flex items-center justify-center size-6 rounded text-xs font-mono ${
                                isSelected ? 'bg-brand-blue text-white font-medium' : 'bg-fill-secondary text-muted'
                            }`}
                        >
                            {point}
                        </span>
                    )
                })}
            </div>
        </div>
    )
}
