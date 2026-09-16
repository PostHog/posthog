// Plain pull request counts for a delivery scope. No repo figure on purpose: comparing how much an author
// or a team ships ranks people, and these counts are only the denominators for the cards next to it.

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import type { DeliverySummaryApi } from '../generated/api.schemas'

export function PullRequestCountsCard({
    summary,
    loading,
}: {
    summary: DeliverySummaryApi | null
    loading: boolean
}): JSX.Element {
    const lines: [string, string][] = summary
        ? [
              ['Opened', String(summary.opened_pr_count)],
              [
                  'Deployed',
                  summary.lead_time.deploy_data_available ? String(summary.lead_time.deployed_merged_pr_count) : '—',
              ],
          ]
        : []

    return (
        <LemonCard hoverEffect={false} className="flex flex-col p-4">
            <h3 className="mb-1 text-xs font-semibold text-secondary">
                <Tooltip title="Counts only, with no repo figure: how many pull requests someone ships is not friction, and comparing it would rank people. Merged and deployed count bots and drafts out.">
                    <span className="cursor-default">Pull requests in the window</span>
                </Tooltip>
            </h3>
            {loading || !summary ? (
                <LemonSkeleton className="h-20 w-full" />
            ) : (
                <>
                    <div className="mb-2 flex items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">
                            {summary.merged_pr_count}
                        </span>
                        <span className="text-xs text-tertiary">merged</span>
                    </div>
                    <div className="flex flex-col">
                        {lines.map(([label, value]) => (
                            <div
                                key={label}
                                className="flex justify-between gap-2 border-t border-primary py-0.5 text-xs text-secondary"
                            >
                                <span>{label}</span>
                                <span className="font-semibold tabular-nums text-primary">{value}</span>
                            </div>
                        ))}
                    </div>
                </>
            )}
        </LemonCard>
    )
}
