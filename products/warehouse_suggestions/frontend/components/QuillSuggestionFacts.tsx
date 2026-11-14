import { ReactNode } from 'react'

import { Card, CardContent, Text } from '@posthog/quill'

export interface SuggestionFact {
    label: string
    value: ReactNode
    details?: ReactNode[]
}

export interface QuillSuggestionFactsProps {
    facts: SuggestionFact[]
    footer?: ReactNode
}

export function QuillSuggestionFacts({ facts, footer }: QuillSuggestionFactsProps): JSX.Element {
    return (
        <Card size="sm">
            <CardContent className="flex flex-col gap-3">
                {facts.map(({ label, value, details = [] }) => (
                    <div key={label} className="flex flex-col gap-0.5">
                        <Text size="xs" weight="semibold" variant="muted" className="m-0">
                            {label}
                        </Text>
                        <Text size="sm" className="m-0">
                            {value}
                        </Text>
                        {details.map((detail, index) => (
                            <Text key={index} size="xs" variant="muted" className="m-0">
                                {detail}
                            </Text>
                        ))}
                    </div>
                ))}
                {footer}
            </CardContent>
        </Card>
    )
}
