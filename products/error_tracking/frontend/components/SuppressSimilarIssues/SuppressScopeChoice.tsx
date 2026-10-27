import { Field, FieldContent, FieldDescription, FieldLabel, FieldTitle, RadioGroupItem, Skeleton } from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'

import { MessagePattern } from './MessagePattern'
import { ScopeImpact, SuppressScopeOption } from './suppressSimilarScopes'

export interface SuppressScopeChoiceProps {
    option: SuppressScopeOption
    title: string
    impact: ScopeImpact | undefined
    impactLoading: boolean
}

export function SuppressScopeChoice({ option, title, impact, impactLoading }: SuppressScopeChoiceProps): JSX.Element {
    const id = `suppress-similar-scope-${option.key}`
    const unavailable = !!option.unavailableReason

    return (
        <FieldLabel htmlFor={id} className="w-full">
            <Field orientation="horizontal" data-disabled={unavailable}>
                <FieldContent className="min-w-0 gap-1.5">
                    <FieldTitle>{title}</FieldTitle>
                    {!unavailable && option.messages.length > 0 && (
                        <span className="flex flex-wrap gap-1">
                            {option.messages.map((segments, index) => (
                                <MessagePattern key={index} segments={segments} />
                            ))}
                        </span>
                    )}
                    {unavailable ? (
                        <FieldDescription className="m-0">{option.unavailableReason}</FieldDescription>
                    ) : impactLoading ? (
                        <Skeleton className="h-4 w-44" />
                    ) : impact ? (
                        <FieldDescription className="m-0">
                            {`${pluralize(impact.exceptions, 'exception')} across ${pluralize(impact.issueCount, 'issue')} in the last 7 days`}
                        </FieldDescription>
                    ) : (
                        <FieldDescription className="m-0">Couldn't count matching exceptions</FieldDescription>
                    )}
                </FieldContent>
                <RadioGroupItem
                    value={option.key}
                    id={id}
                    disabled={unavailable}
                    data-attr={`error-tracking-suppress-similar-scope-${option.key}`}
                />
            </Field>
        </FieldLabel>
    )
}
