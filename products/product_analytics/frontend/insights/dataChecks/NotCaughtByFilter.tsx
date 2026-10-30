import { Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

export function NotCaughtByFilter({
    count,
    noun,
    examples,
    fallback,
    predicate,
    explanation,
}: {
    count: number
    noun: string
    examples: string[]
    /** The subject when no count is known. */
    fallback: string
    predicate: string
    explanation: string | null
}): JSX.Element {
    const others = Math.max(count - examples.length, 0)
    return (
        <div className="flex flex-col gap-1.5">
            <Text size="xs" variant="muted">
                {count > 0 && examples.length > 0 ? (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <button
                                    type="button"
                                    className="cursor-default border-0 bg-transparent p-0 text-inherit underline decoration-dotted underline-offset-2"
                                    data-attr={`insight-data-check-${noun}-examples`}
                                />
                            }
                        >
                            {pluralize(count, noun)}
                        </TooltipTrigger>
                        <TooltipContent>
                            <span className="flex flex-col">
                                {examples.map((example) => (
                                    <span key={example}>{example}</span>
                                ))}
                                {others > 0 && <span>{`and ${pluralize(others, 'other')}`}</span>}
                            </span>
                        </TooltipContent>
                    </Tooltip>
                ) : (
                    <span>{count > 0 ? pluralize(count, noun) : fallback}</span>
                )}
                <span>{` ${predicate}`}</span>
            </Text>
            {explanation && (
                <Text size="xs" variant="muted">
                    {explanation}
                </Text>
            )}
        </div>
    )
}
