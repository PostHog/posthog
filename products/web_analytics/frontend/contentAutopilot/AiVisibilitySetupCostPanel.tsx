import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@posthog/quill'

import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { CheckFrequencyEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { CostRange, estimateCost } from './checkCosts'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { frequencyLabel } from './engineFrequency'
import { engineLabel } from './utils'

// A maximum from the 90th-percentile cost per check, since most checks cost less and a budget needs the top end.
const upTo = ({ high }: CostRange, precision: number): string => `up to about ${humanFriendlyCurrency(high, precision)}`

export const AiVisibilitySetupCostPanel = ({
    prompts,
    engines,
}: {
    prompts: number
    engines: { engine: string; frequency: CheckFrequencyEnumApi }[]
}): JSX.Element => {
    const estimate = estimateCost(prompts, engines)

    return (
        <Card size="sm" data-attr="ai-visibility-setup-cost-panel" data-checks={estimate.checksPerRun}>
            <CardHeader>
                <CardTitle role="heading" aria-level={4}>
                    Estimated cost
                </CardTitle>
                <CardDescription>
                    Each check asks the engine with web search on. It runs its own searches and reads the pages, so you
                    see the same answer your buyers see, and that's what a check pays for. Keywords don't add checks.
                </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
                <ul className="m-0 flex list-none flex-col gap-3 p-0">
                    {estimate.engines.map((row) => (
                        <li key={row.engine} className="flex items-start justify-between gap-3">
                            <span className="flex flex-col">
                                <ContentAutopilotEngineLabel engine={row.engine} />
                                <span className="text-xs text-muted-foreground">
                                    {frequencyLabel(row.frequency)}, {pluralize(row.checks, 'check')} per run
                                </span>
                            </span>
                            <span className="shrink-0 text-right whitespace-nowrap tabular-nums">
                                {row.perRun ? upTo(row.perRun, 2) : 'Not priced'}
                            </span>
                        </li>
                    ))}
                    {estimate.engines.length === 0 ? (
                        <li className="text-muted-foreground">No engine is on, so nothing runs.</li>
                    ) : null}
                </ul>

                <dl className="m-0 flex flex-col gap-2 border-t pt-3">
                    <div className="flex items-baseline justify-between gap-3">
                        <dt className="flex flex-col">
                            <span className="text-muted-foreground">Checks per run</span>
                            <span className="text-xs text-muted-foreground">
                                {pluralize(prompts, 'prompt')} × {pluralize(engines.length, 'engine')}
                            </span>
                        </dt>
                        <dd className="m-0 tabular-nums" data-attr="ai-visibility-setup-cost-checks">
                            {estimate.checksPerRun}
                        </dd>
                    </div>
                    <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-muted-foreground">Per run</dt>
                        <dd className="m-0 tabular-nums">{upTo(estimate.perRun, 2)}</dd>
                    </div>
                    <div className="flex items-baseline justify-between gap-3">
                        <dt className="font-semibold">Per month</dt>
                        <dd
                            className="m-0 text-lg font-semibold tabular-nums"
                            data-attr="ai-visibility-setup-cost-month"
                        >
                            {upTo(estimate.perMonth, 0)}
                        </dd>
                    </div>
                </dl>
            </CardContent>

            <CardFooter className="text-xs text-muted-foreground">
                <p className="m-0">
                    Approximate maximums from measured checks, using a long answer (the 90th percentile). It's usually
                    less. A month counts 30 daily runs, 10 every 72 hours, or about 4 weekly ones.
                    {estimate.unpriced.length > 0
                        ? ` ${estimate.unpriced.map(engineLabel).join(' and ')} ${estimate.unpriced.length === 1 ? "isn't" : "aren't"} included.`
                        : ''}
                </p>
            </CardFooter>
        </Card>
    )
}
