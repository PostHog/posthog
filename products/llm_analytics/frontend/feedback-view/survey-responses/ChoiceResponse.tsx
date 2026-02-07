import { SurveyQuestion } from '~/types'

export function ChoiceResponse({ value, question }: { value: unknown; question: SurveyQuestion }): JSX.Element {
    const choices = Array.isArray(value)
        ? value
        : String(value)
              .split(',')
              .map((s) => s.trim())

    return (
        <div className="flex flex-col gap-2">
            {question.question && <span className="text-xs text-muted">{question.question}</span>}
            <div className="flex flex-wrap gap-1.5">
                {choices.map((choice, i) => (
                    <span
                        key={i}
                        className="inline-flex items-center px-2 py-0.5 rounded-md bg-fill-secondary text-sm text-primary"
                    >
                        {choice}
                    </span>
                ))}
            </div>
        </div>
    )
}
