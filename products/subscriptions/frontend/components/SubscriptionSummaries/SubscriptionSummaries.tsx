import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { subscriptionSummariesLogic, type SubscriptionSummariesLogicProps } from './subscriptionSummariesLogic'
import { SubscriptionSummaryEntry } from './SubscriptionSummaryEntry'

interface SubscriptionSummariesProps extends SubscriptionSummariesLogicProps {
    className?: string
}

export function SubscriptionSummaries({ className, ...props }: SubscriptionSummariesProps): JSX.Element | null {
    const logic = subscriptionSummariesLogic(props)
    const { latestSummary, earlierSummaries, historyExpanded } = useValues(logic)
    const { toggleHistory } = useActions(logic)

    // Most dashboards and insights have no summaries, so nothing renders until summaries exist.
    if (!latestSummary) {
        return null
    }

    return (
        <div
            className={cn('border rounded bg-surface-primary p-3 flex flex-col gap-2', className)}
            data-attr="subscription-summaries"
        >
            <div className="flex items-center gap-2 font-semibold">
                <IconSparkles className="text-accent" />
                Latest AI summary
            </div>
            <SubscriptionSummaryEntry summary={latestSummary} />
            {earlierSummaries.length > 0 && (
                <>
                    <div>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={historyExpanded ? <IconChevronDown /> : <IconChevronRight />}
                            onClick={toggleHistory}
                            data-attr="subscription-summaries-history-toggle"
                        >
                            {historyExpanded
                                ? 'Hide earlier summaries'
                                : `Show ${pluralize(earlierSummaries.length, 'earlier summary', 'earlier summaries')}`}
                        </LemonButton>
                    </div>
                    {historyExpanded && (
                        <div className="flex flex-col gap-3 max-h-96 overflow-y-auto">
                            {earlierSummaries.map((summary) => (
                                <div key={summary.id} className="flex flex-col gap-3">
                                    <LemonDivider className="my-0" />
                                    <SubscriptionSummaryEntry summary={summary} />
                                </div>
                            ))}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
