import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Text,
} from '@posthog/quill'

import type { ConversionRecommendationApi } from '../generated/api.schemas'

export function QuillConversionRecommendationCard({
    recommendation,
    onUseSuggestion,
    onDismiss,
    disabledReason,
}: {
    recommendation: ConversionRecommendationApi
    onUseSuggestion: () => void
    onDismiss?: () => void
    disabledReason?: string | null
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-wrap items-start gap-2 py-2">
            <Collapsible className="min-w-0 flex-1 basis-64">
                <CollapsibleHeader className="items-start py-1">
                    <CollapsibleTrigger iconOnly>{recommendation.name}</CollapsibleTrigger>
                    <div className="flex min-w-0 flex-col gap-1">
                        <Text size="xs" weight="semibold" render={<span className="m-0 break-words" />}>
                            {recommendation.name}
                        </Text>
                        {/* The badge sits on its own line in every row, so rows keep one height at any width. */}
                        <div className="flex flex-wrap items-center gap-2">
                            <Badge>
                                {recommendation.intent === 'revenue'
                                    ? 'Potential revenue goal'
                                    : recommendation.intent === 'customer'
                                      ? 'Potential customer goal'
                                      : 'Potential conversion goal'}
                            </Badge>
                            <Text size="xs" variant="muted" render={<span className="m-0 break-all" />}>
                                <span>{recommendation.candidate.name}</span>
                                {recommendation.candidate.count != null && (
                                    <span>{` · ${recommendation.candidate.count.toLocaleString()} events`}</span>
                                )}
                            </Text>
                        </div>
                    </div>
                </CollapsibleHeader>
                <CollapsibleContent className="flex flex-col gap-2 break-words">
                    <Text size="xs" render={<p className="m-0" />}>
                        {recommendation.reason}
                    </Text>
                    {recommendation.amount_property && (
                        <Text
                            size="xs"
                            variant="muted"
                            render={<p className="m-0" />}
                        >{`Amount property: ${recommendation.amount_property}`}</Text>
                    )}
                    {recommendation.questions.length > 0 && (
                        <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-xs">
                            {recommendation.questions.map((question, index) => (
                                <li key={index}>{question}</li>
                            ))}
                        </ul>
                    )}
                </CollapsibleContent>
            </Collapsible>
            <div className="ml-auto flex flex-wrap items-center gap-1">
                <Button
                    variant="outline"
                    onClick={onUseSuggestion}
                    disabledReason={disabledReason}
                    data-attr="marketing-conversion-use-suggestion"
                >
                    Review suggestion
                </Button>
                {onDismiss && (
                    <Button variant="outline" onClick={onDismiss} data-attr="marketing-conversion-dismiss-suggestion">
                        Dismiss
                    </Button>
                )}
            </div>
        </div>
    )
}
