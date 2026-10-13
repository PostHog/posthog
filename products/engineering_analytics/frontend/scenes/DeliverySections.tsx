import { useActions, useValues } from 'kea'

import { pluralize } from 'lib/utils/strings'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { LeadTimeComparisonCard } from '../components/LeadTimeComparisonCard'
import { PullRequestCountsCard } from '../components/PullRequestCountsCard'
import { ReadyToMergeCard } from '../components/ReadyToMergeCard'
import { ScopeComparisonCard } from '../components/ScopeComparisonCard'
import { Section } from '../components/Section'
import type { DeliveryComparisonApi } from '../generated/api.schemas'
import { DeliveryScope } from '../lib/deliveryScope'
import { compactMinutes, compactUsd, percent } from '../lib/format'
import { missingTeamText, summaryRows, teamRows } from '../lib/readyToMergeRows'
import { deliverySummaryLogic } from './deliverySummaryLogic'

const formatRatio = (value: number): string => value.toFixed(1)

export function DeliverySections({
    scope,
    scopeLabel,
    sourceId,
    comparison = null,
    comparisonFailed = false,
}: {
    /** An author or a GitHub team; the summary endpoint rejects a single pull request. */
    scope: DeliveryScope
    scopeLabel: string
    sourceId: string | null
    /** An author's comparison with their own team, which adds the team's row to the ready-to-merge card. */
    comparison?: DeliveryComparisonApi | null
    comparisonFailed?: boolean
}): JSX.Element {
    const summaryLogic = deliverySummaryLogic({ scope, sourceId })
    const { summary, summaryLoading, summaryFailed } = useValues(summaryLogic)
    const { loadSummary } = useActions(summaryLogic)

    if (summaryFailed) {
        return <CIAnalyticsLoadError onRetry={loadSummary} />
    }

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
                        <PullRequestCountsCard summary={summary} loading={summaryLoading} />
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
                            loading={summaryLoading}
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
                            loading={summaryLoading}
                            emptyText={costEmpty}
                        />
                        <ScopeComparisonCard
                            title="Cost per push"
                            tooltip="CI cost of merged pull requests, merge queue runs included, divided by their pushes. A push is a new head commit and the CI it started. A high figure points at heavy workflows rather than many pushes."
                            scopeLabel={scopeLabel}
                            figure={summary?.cost_per_push_usd}
                            formatValue={compactUsd}
                            caption={summary ? pluralize(summary.push_count, 'push', 'pushes') : undefined}
                            loading={summaryLoading}
                            emptyText={costEmpty}
                        />
                    </div>
                </div>
            </Section>

            <Section id="delivery-merge" title="Getting merged">
                <div className="@container">
                    <div className="grid grid-cols-1 gap-2 @min-[36rem]:grid-cols-2 @min-[64rem]:grid-cols-4">
                        <div className="@min-[36rem]:col-span-2">
                            <ReadyToMergeCard
                                rows={
                                    summary
                                        ? summaryRows(
                                              summary,
                                              scopeLabel,
                                              teamRows(comparisonFailed ? null : comparison)
                                          )
                                        : []
                                }
                                reviewsSynced={!!summary?.review_data_available}
                                loading={summaryLoading}
                                emptyText={
                                    summary && !summary.ready_data_available
                                        ? 'Ready time appears once the issue events table on this GitHub source is synced.'
                                        : 'No merged pull requests with a known ready time in the window.'
                                }
                                footnote={missingTeamText(comparison, comparisonFailed)}
                            />
                        </div>
                        <ScopeComparisonCard
                            title="Pushes after approval"
                            tooltip="Average pushes after the first approval, per merged pull request that had an approval. A push is a new head commit that started CI."
                            scopeLabel={scopeLabel}
                            figure={summary?.pushes_after_approval_per_merged_pr}
                            formatValue={formatRatio}
                            loading={summaryLoading}
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
                            loading={summaryLoading}
                            emptyText="No merged pull requests went through the merge queue in the window."
                        />
                    </div>
                </div>
            </Section>

            <Section id="delivery-lead-time" title="Lead time to deploy">
                <LeadTimeComparisonCard
                    leadTime={summary?.lead_time}
                    scopeLabel={scopeLabel}
                    loading={summaryLoading}
                />
            </Section>
        </>
    )
}
