import type { ReactElement } from 'react'

import { Badge, Stack } from '@posthog/mosaic'

export interface SurveyQuestionData {
    type: string
    question: string
    description?: string | null
    choices?: string[] | null
    scale?: number | null
    lowerBoundLabel?: string | null
    upperBoundLabel?: string | null
    branching?: Record<string, unknown> | null
}

export interface SurveyQuestionProps {
    question: SurveyQuestionData
    index: number
}

const typeLabels: Record<string, string> = {
    open: 'Open text',
    multiple_choice: 'Multiple choice',
    single_choice: 'Single choice',
    rating: 'Rating',
    link: 'Link',
    nps: 'NPS',
}

export function SurveyQuestion({ question, index }: SurveyQuestionProps): ReactElement {
    return (
        <Stack gap="xs">
            <div className="flex items-center gap-2">
                <span className="text-xs text-text-secondary">Q{index + 1}</span>
                <Badge variant="neutral" size="sm">
                    {typeLabels[question.type] ?? question.type}
                </Badge>
            </div>
            <span className="text-sm text-text-primary">{question.question}</span>
            {question.description && <span className="text-xs text-text-secondary">{question.description}</span>}
            {question.choices && question.choices.length > 0 && (
                <ul className="list-disc list-inside text-xs text-text-secondary pl-2">
                    {question.choices.map((choice, i) => (
                        <li key={i}>{choice}</li>
                    ))}
                </ul>
            )}
            {question.type === 'rating' && question.scale && (
                <span className="text-xs text-text-secondary">
                    Scale: 1&ndash;{question.scale}
                    {question.lowerBoundLabel && ` (${question.lowerBoundLabel}`}
                    {question.upperBoundLabel && ` to ${question.upperBoundLabel})`}
                </span>
            )}
        </Stack>
    )
}
