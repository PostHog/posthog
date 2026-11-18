import { Card, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { SetupFact } from './setupFact'

export function QuillSetupFactsTable({ facts }: { facts: SetupFact[] }): JSX.Element {
    return (
        <Card size="sm" flush className="py-0">
            <dl className="m-0 divide-y divide-border">
                {facts.map((fact) => (
                    <div key={fact.label} className="grid grid-cols-[40%_1fr] gap-3 px-3 py-1.5">
                        <Text size="sm" variant="muted" render={<dt />}>
                            {fact.help ? (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={<span className="underline decoration-dotted" tabIndex={0} />}
                                    >
                                        {fact.label}
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-80">{fact.help}</TooltipContent>
                                </Tooltip>
                            ) : (
                                fact.label
                            )}
                        </Text>
                        <Text size="sm" render={<dd className="m-0 min-w-0 break-words" translate="no" />}>
                            {fact.value}
                        </Text>
                    </div>
                ))}
            </dl>
        </Card>
    )
}
