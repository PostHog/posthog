// One pull request's ready-to-merged time next to the medians of the pull requests merged in the 30 days
// before it: its author's, the author's own team's, and the repository's.

import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'

import type { DeliveryComparisonApi, PRTimelineApi } from '../generated/api.schemas'
import { timeInStates } from '../lib/pullRequestTimeline'
import { ReadyToMergeRow, mediansRow, missingTeamText, teamRows } from '../lib/readyToMergeRows'
import { deliveryComparisonLogic } from '../scenes/deliveryComparisonLogic'
import { ReadyToMergeCard } from './ReadyToMergeCard'

const WINDOW_DAYS = 30

function pullRequestRow(pr: PRTimelineApi, comparison: DeliveryComparisonApi): ReadyToMergeRow {
    const split = comparison.pull_request
    return {
        label: pr.merged_at ? 'This PR' : 'This PR so far',
        shortLabel: 'this PR',
        // An open pull request's timeline starts at its last ready for review, the medians' measure so far.
        // A merged one keeps the read's own measure, which is null when its ready time was not observed.
        seconds: pr.merged_at ? (split?.ready_to_merge_seconds ?? null) : timeInStates(pr).wholeSeconds,
        p90Seconds: null,
        beforeShare: split?.before_first_approval_share ?? null,
        beforeApprovalSeconds: split?.ready_to_first_approval_seconds ?? null,
        afterApprovalSeconds: split?.first_approval_to_merge_seconds ?? null,
    }
}

export function PullRequestComparisonCard({
    pr,
    sourceId,
}: {
    pr: PRTimelineApi
    sourceId: string | null
}): JSX.Element {
    const dateWindow = pr.merged_at
        ? { dateFrom: dayjs(pr.merged_at).subtract(WINDOW_DAYS, 'day').toISOString(), dateTo: pr.merged_at }
        : { dateFrom: `-${WINDOW_DAYS}d`, dateTo: null }
    const { comparison, comparisonLoading, comparisonFailed } = useValues(
        deliveryComparisonLogic({
            author: pr.author.handle,
            sourceId,
            prNumber: pr.number,
            repo: `${pr.repo.owner}/${pr.repo.name}`,
            window: dateWindow,
        })
    )
    const handle = pr.author.handle
    const rows = comparison
        ? [
              pullRequestRow(pr, comparison),
              mediansRow(handle, handle, comparison.author_medians),
              ...teamRows(comparison),
              mediansRow('Repo', 'repo', comparison.repo_medians),
          ]
        : []

    return (
        <ReadyToMergeCard
            title="Compared with recent pull requests"
            tooltip={`This pull request's time from ready for review to merged, next to the medians over pull requests merged in the ${WINDOW_DAYS} days before it: its author's, the author's own team's, and the whole repository's. Each bar is split at the first approval by the share of hours on each side.`}
            rows={rows}
            reviewsSynced={!!comparison?.review_data_available}
            loading={comparisonLoading && !comparison}
            emptyText={
                comparisonFailed
                    ? "Couldn't load the comparison. Reload the page to try again."
                    : "This pull request's ready for review time isn't known, so there is nothing to compare."
            }
            footnote={missingTeamText(comparison, false)}
            dataAttr="engineering-analytics-pr-comparison"
        />
    )
}
