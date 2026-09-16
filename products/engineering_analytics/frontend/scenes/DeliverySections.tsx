// The delivery sections for one author or GitHub team, inside a page's ScopePanel: CI spend, getting
// merged, and lead time to deploy, each figure against the repository.

import { useActions, useValues } from 'kea'

import { dateMapping } from 'lib/utils/dateFilters'
import { pluralize } from 'lib/utils/strings'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { LeadTimeComparisonCard } from '../components/LeadTimeComparisonCard'
import { PullRequestCountsCard } from '../components/PullRequestCountsCard'
import { ReadyToMergeCard } from '../components/ReadyToMergeCard'
import { ScopeComparisonCard } from '../components/ScopeComparisonCard'
import { Section } from '../components/Section'
import { DeliveryScope } from '../lib/deliveryScope'
import { compactMinutes, compactUsd, percent } from '../lib/format'
import { deliverySummaryLogic } from './deliverySummaryLogic'

// Relative presets only: the backend caps a window at a year, and every preset here stays inside it.
export const DELIVERY_DATE_OPTIONS = dateMapping.filter(({ key }) =>
    ['Last 7 days', 'Last 14 days', 'Last 30 days', 'Last 90 days', 'Last 180 days', 'This year'].includes(key)
)

const formatRatio = (value: number): string => value.toFixed(1)

export function DeliverySections({
    scope,
    scopeLabel,
    sourceId,
}: {
    /** An author or a GitHub team; the summary endpoint rejects a single pull request. */
    scope: DeliveryScope
    /** The row label for the scope's bars, e.g. "This author" or "This team". */
    scopeLabel: string
    sourceId: string | null
}): JSX.Element {
    const summaryLogic = deliverySummaryLogic({ scope, sourceId })
    const { summary, summaryLoading, summaryFailed } = useValues(summaryLogic)
    const { loadSummary } = useActions(summaryLogic)

    if (summaryFailed) {
        return <CIAnalyticsLoadError onRetry={loadSummary} />
    }

    // Without the members table a team matches no author, so every figure would read as a false zero.
    if (summary?.scope_kind === 'github_team' && !summary.has_membership_data) {
        return (
            <div className="py-8 text-center text-sm text-secondary">
                No team membership data. Sync the team members table on this GitHub source to see this team's delivery
                figures.
            </div>
        )
    }

    const summaryPending = summaryLoading && !summary
    const costEmpty =
        summary && !summary.jobs_available
            ? 'Cost appears once the workflow jobs table on this GitHub source is synced.'
            : 'Nothing merged in the window.'
    const reviewsEmpty =
        summary && !summary.review_data_available
            ? 'Sync the reviews table on this GitHub source to see pushes after the first approval.'
            : 'No approved pull requests merged in the window.'

    return (
        <>
            <Section id="delivery-spend" title="CI spend">
                <div className="@container">
                    <div className="grid grid-cols-1 gap-2 @min-[36rem]:grid-cols-2 @min-[64rem]:grid-cols-4">
                        <PullRequestCountsCard summary={summary} loading={summaryPending} />
                        <ScopeComparisonCard
                            title="CI cost per merged PR"
                            tooltip="Median estimated CI cost of a merged pull request: every run linked to it, merge queue runs included, from up to 30 days before the window. Repo: the same median over every pull request merged in the repository, bots excluded."
                            scopeLabel={scopeLabel}
                            figure={summary?.cost_per_merged_pr_usd}
                            formatValue={compactUsd}
                            caption={
                                summary?.total_cost_usd != null
                                    ? `${compactUsd(summary.total_cost_usd)} in total`
                                    : undefined
                            }
                            loading={summaryPending}
                            emptyText={costEmpty}
                        />
                        <ScopeComparisonCard
                            title="Billable minutes per merged PR"
                            tooltip="Median billed runner minutes of a merged pull request, on the billed clock (machine boot left out). Re-run copies that never ran again are not counted."
                            scopeLabel={scopeLabel}
                            figure={summary?.billable_minutes_per_merged_pr}
                            formatValue={compactMinutes}
                            caption={
                                summary?.total_billable_minutes != null
                                    ? `${compactMinutes(summary.total_billable_minutes)} billable in total`
                                    : undefined
                            }
                            loading={summaryPending}
                            emptyText={costEmpty}
                        />
                        <ScopeComparisonCard
                            title="Cost per push"
                            tooltip="CI cost divided by pushes. A push is a new commit and the CI it started: the price of one iteration, so a high figure points at heavy workflows rather than many pushes."
                            scopeLabel={scopeLabel}
                            figure={summary?.cost_per_push_usd}
                            formatValue={compactUsd}
                            caption={summary ? pluralize(summary.push_count, 'push', 'pushes') : undefined}
                            loading={summaryPending}
                            emptyText={costEmpty}
                        />
                    </div>
                </div>
            </Section>

            <Section id="delivery-merge" title="Getting merged">
                <div className="@container">
                    <div className="grid grid-cols-1 gap-2 @min-[36rem]:grid-cols-2 @min-[64rem]:grid-cols-4">
                        <div className="@min-[36rem]:col-span-2">
                            <ReadyToMergeCard summary={summary} scopeLabel={scopeLabel} loading={summaryPending} />
                        </div>
                        <ScopeComparisonCard
                            title="Pushes after approval"
                            tooltip="Average new commits pushed after the first approval, per merged pull request that had an approval."
                            scopeLabel={scopeLabel}
                            figure={summary?.pushes_after_approval_per_merged_pr}
                            formatValue={formatRatio}
                            loading={summaryPending}
                            emptyText={reviewsEmpty}
                        />
                        <ScopeComparisonCard
                            title="Merge queue attempts"
                            tooltip="Average merge queue attempts per merged pull request that went through the queue. 1.0 means every pull request landed on its first try. A failed attempt also counts when another pull request ahead in the queue broke it: the queue's history isn't in the warehouse, so the two can't be told apart."
                            scopeLabel={scopeLabel}
                            figure={summary?.merge_queue_attempts_per_merged_pr}
                            formatValue={formatRatio}
                            caption={
                                summary?.failed_merge_queue_share.scope != null
                                    ? `${percent(summary.failed_merge_queue_share.scope)} had a failed attempt · repo ${percent(summary.failed_merge_queue_share.repo)}`
                                    : undefined
                            }
                            loading={summaryPending}
                            emptyText="No merged pull requests went through the merge queue in the window."
                        />
                    </div>
                </div>
            </Section>

            <Section id="delivery-lead-time" title="Lead time to deploy">
                <LeadTimeComparisonCard
                    leadTime={summary?.lead_time}
                    scopeLabel={scopeLabel}
                    loading={summaryPending}
                />
            </Section>
        </>
    )
}
