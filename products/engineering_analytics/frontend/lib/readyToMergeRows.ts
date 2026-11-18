import type { DeliveryComparisonApi, DeliverySummaryApi, ReadyToMergeMediansApi } from '../generated/api.schemas'

export interface ReadyToMergeRow {
    label: string
    /** The row's name in the baseline text under the bars, e.g. "repo". */
    shortLabel: string
    labelTooltip?: string
    seconds: number | null
    p90Seconds: number | null
    beforeShare: number | null
    beforeApprovalSeconds: number | null
    afterApprovalSeconds: number | null
}

export function mediansRow(
    label: string,
    shortLabel: string,
    medians: ReadyToMergeMediansApi,
    labelTooltip?: string
): ReadyToMergeRow {
    return {
        label,
        shortLabel,
        labelTooltip,
        seconds: medians.ready_to_merge_seconds,
        p90Seconds: medians.p90_ready_to_merge_seconds,
        beforeShare: medians.before_first_approval_share,
        beforeApprovalSeconds: medians.ready_to_first_approval_seconds,
        afterApprovalSeconds: medians.first_approval_to_merge_seconds,
    }
}

export function summaryRows(
    summary: DeliverySummaryApi,
    scopeLabel: string,
    teamRows: ReadyToMergeRow[] = []
): ReadyToMergeRow[] {
    const row = (pick: 'scope' | 'repo', label: string, shortLabel: string): ReadyToMergeRow => ({
        label,
        shortLabel,
        seconds: summary.median_ready_to_merge_seconds[pick],
        p90Seconds: summary.p90_ready_to_merge_seconds[pick],
        beforeShare: summary.before_first_approval_share[pick],
        beforeApprovalSeconds: summary.median_ready_to_first_approval_seconds[pick],
        afterApprovalSeconds: summary.median_first_approval_to_merge_seconds[pick],
    })
    return [row('scope', scopeLabel, scopeLabel.toLowerCase()), ...teamRows, row('repo', 'Repo', 'repo')]
}

function teamTooltip(comparison: DeliveryComparisonApi, team: string): string {
    const author = comparison.author
    switch (comparison.team_basis) {
        case 'pull_request':
            return `${team}: this pull request asked the team to review.`
        case 'review_requests':
            return `${team}: the team ${author}'s pull requests asked to review most often.`
        case 'only_team':
            return `${team}: ${author}'s team.`
        default:
            return `${team}: one of ${author}'s teams. No review request points at one of them.`
    }
}

export function teamRows(comparison: DeliveryComparisonApi | null): ReadyToMergeRow[] {
    if (!comparison) {
        return []
    }
    return comparison.teams.flatMap(({ github_team, medians }) =>
        medians ? [mediansRow(github_team, github_team, medians, teamTooltip(comparison, github_team))] : []
    )
}

export function missingTeamText(comparison: DeliveryComparisonApi | null, failed: boolean): string | null {
    if (failed) {
        return "Couldn't load the team comparison. Reload the page to try again."
    }
    if (!comparison) {
        return null
    }
    if (comparison.teams.length === 0) {
        return comparison.has_membership_data
            ? `No team row: ${comparison.author} isn't in a team that owns code.`
            : "Sync the team members table on this GitHub source to compare with the author's team."
    }
    const hidden = comparison.teams.filter((team) => !team.medians).map((team) => team.github_team)
    return hidden.length
        ? `No row for ${hidden.join(', ')}: fewer than three other authors merged there in the window, so a median would show a teammate's time.`
        : null
}
