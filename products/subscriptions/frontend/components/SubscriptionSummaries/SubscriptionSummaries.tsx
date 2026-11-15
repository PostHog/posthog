import { useActions, useValues } from 'kea'

import { IconChevronDown, IconSparkles } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { subscriptionSummariesLogic, type SubscriptionSummariesLogicProps } from './subscriptionSummariesLogic'
import { SubscriptionSummaryEntry } from './SubscriptionSummaryEntry'

interface SubscriptionSummariesProps extends SubscriptionSummariesLogicProps {
    className?: string
}

export function SubscriptionSummaries({ className, ...props }: SubscriptionSummariesProps): JSX.Element | null {
    const logic = subscriptionSummariesLogic(props)
    const { latestSummary, collapsed } = useValues(logic)
    const { toggleCollapsed } = useActions(logic)

    // Most dashboards and insights have no summaries, so nothing renders until summaries exist.
    if (!latestSummary) {
        return null
    }

    return (
        <div
            className={cn('border rounded bg-surface-primary p-3 flex flex-col gap-2', className)}
            data-attr="subscription-summaries"
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                    type="button"
                    className="flex items-center gap-2 font-semibold cursor-pointer"
                    onClick={toggleCollapsed}
                    aria-expanded={!collapsed}
                    data-attr="subscription-summaries-toggle"
                >
                    <IconChevronDown className={cn('text-secondary transition-transform', collapsed && '-rotate-90')} />
                    <IconSparkles className="text-accent" />
                    Latest AI summary
                </button>
                <Link
                    to={urls.subscription(latestSummary.subscription)}
                    className="text-xs"
                    data-attr="subscription-summaries-delivery-history-link"
                >
                    View delivery history
                </Link>
            </div>
            {!collapsed && <SubscriptionSummaryEntry summary={latestSummary} />}
        </div>
    )
}
