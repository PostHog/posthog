import {
    PinReasonEnumApi,
    RoutingOwnerOutcomeEnumApi,
    RoutingOwnerReasonEnumApi,
    StamphogRoutingRunApi,
    StamphogRoutingRunOwnerApi,
    type StamphogRoutingRunsListParams,
} from '../../generated/api.schemas'

export type AreaFilter = 'all' | 'merged_without_team' | 'team_asked'

export const AREA_FILTER_OPTIONS: { value: AreaFilter; label: string }[] = [
    { value: 'all', label: 'All changes' },
    { value: 'merged_without_team', label: 'Merged without your team' },
    { value: 'team_asked', label: 'Your team was asked' },
]

export const DEFAULT_AREA_FILTER: AreaFilter = 'all'

/**
 * The outcomes that mean the team was asked. Besides `requested`, the team was asked on an earlier run
 * (`already_requested`) or by label on a fork pull request (`labeled`).
 */
const ASKED_OUTCOMES: RoutingOwnerOutcomeEnumApi[] = [
    RoutingOwnerOutcomeEnumApi.Requested,
    RoutingOwnerOutcomeEnumApi.AlreadyRequested,
    RoutingOwnerOutcomeEnumApi.Labeled,
]

/** The outcome filter each segment sends. "All changes" sends none. */
export const AREA_FILTER_OUTCOMES: Record<AreaFilter, StamphogRoutingRunsListParams['outcome']> = {
    all: undefined,
    // Matches isMergedWithoutTeam, so the segment lists every pull request the headline counts.
    merged_without_team: [RoutingOwnerOutcomeEnumApi.NotRequested, RoutingOwnerOutcomeEnumApi.Refused],
    team_asked: ASKED_OUTCOMES,
}

export type AreaWindowDays = 7 | 30 | 90

export const AREA_WINDOW_OPTIONS: { value: AreaWindowDays; label: string }[] = [
    { value: 7, label: 'Last 7 days' },
    { value: 30, label: 'Last 30 days' },
    { value: 90, label: 'Last 90 days' },
]

export const DEFAULT_WINDOW_DAYS: AreaWindowDays = 7

/** A pull request that merged without the team and is mostly the team's code needs a look. */
const NEEDS_A_LOOK_SHARE = 0.5

export type AreaGroup = 'needs_a_look' | 'merged_without_team' | 'team_asked' | 'small_part'

const AREA_GROUPS: { key: AreaGroup; title: string }[] = [
    { key: 'needs_a_look', title: 'Needs a look' },
    { key: 'merged_without_team', title: 'Merged without your team' },
    { key: 'team_asked', title: 'Your team was asked' },
    { key: 'small_part', title: "Small parts of other teams' changes" },
]

/** One pull request as the area page shows it: the run, and the run's decision about the picked owner. */
export interface AreaRow {
    run: StamphogRoutingRunApi
    decision: StamphogRoutingRunOwnerApi
}

export function ownerDecision(run: StamphogRoutingRunApi, owner: string): StamphogRoutingRunOwnerApi | null {
    return run.owners.find((entry) => entry.owner === owner) ?? null
}

/** The owner's share of the whole change, or null while the size is unknown (it is stored at merge). */
export function ownedShare(row: AreaRow): number | null {
    const { additions, deletions } = row.run.pull_request
    if (additions == null || deletions == null || additions + deletions === 0) {
        return null
    }
    return Math.min(1, (row.decision.lines ?? 0) / (additions + deletions))
}

export function touchesSensitivePath(decision: StamphogRoutingRunOwnerApi): boolean {
    return decision.pins.some((pin) => pin.reason === PinReasonEnumApi.Sensitive)
}

function isTeamAsked(outcome: RoutingOwnerOutcomeEnumApi): boolean {
    return ASKED_OUTCOMES.includes(outcome)
}

export function isMergedWithoutTeam(outcome: RoutingOwnerOutcomeEnumApi): boolean {
    // GitHub refusing the request leaves the team unasked too.
    return outcome === RoutingOwnerOutcomeEnumApi.NotRequested || outcome === RoutingOwnerOutcomeEnumApi.Refused
}

export function areaGroup(row: AreaRow): AreaGroup {
    const { outcome } = row.decision
    const share = ownedShare(row)
    const mostlyTheirs = share !== null && share >= NEEDS_A_LOOK_SHARE
    if (touchesSensitivePath(row.decision) || (outcome === RoutingOwnerOutcomeEnumApi.NotRequested && mostlyTheirs)) {
        return 'needs_a_look'
    }
    if (isMergedWithoutTeam(outcome)) {
        return 'merged_without_team'
    }
    if (isTeamAsked(outcome)) {
        return 'team_asked'
    }
    return 'small_part'
}

/** Rows in display groups, each group sorted by the owner's changed lines, largest first. Empty groups are left out. */
export function groupAreaRows(
    runs: StamphogRoutingRunApi[],
    owner: string
): { key: AreaGroup; title: string; rows: AreaRow[] }[] {
    const rows: AreaRow[] = []
    for (const run of runs) {
        const decision = ownerDecision(run, owner)
        if (decision) {
            rows.push({ run, decision })
        }
    }
    return AREA_GROUPS.map((group) => ({
        ...group,
        rows: rows
            .filter((row) => areaGroup(row) === group.key)
            .sort((a, b) => (b.decision.lines ?? 0) - (a.decision.lines ?? 0)),
    })).filter((group) => group.rows.length > 0)
}

type StatusTagType = 'warning' | 'info' | 'muted'

export function statusTag(outcome: RoutingOwnerOutcomeEnumApi): { label: string; type: StatusTagType } {
    if (isTeamAsked(outcome)) {
        return { label: 'Your team was asked', type: 'info' }
    }
    if (isMergedWithoutTeam(outcome)) {
        return { label: 'Merged without your team', type: 'warning' }
    }
    return { label: 'Not needed for your team', type: 'muted' }
}

/** Another owner's decision in a few plain words, for the expanded row. */
export function otherOwnerStatus(outcome: RoutingOwnerOutcomeEnumApi): string {
    if (isTeamAsked(outcome)) {
        return 'Asked to review'
    }
    if (isMergedWithoutTeam(outcome)) {
        return 'Not asked'
    }
    return 'Not needed'
}

const REASON_PHRASE: Record<RoutingOwnerReasonEnumApi, string> = {
    [RoutingOwnerReasonEnumApi.Sensitive]: 'it changed a sensitive path your team owns',
    [RoutingOwnerReasonEnumApi.NewPath]: 'it added a new path in code your team owns',
    [RoutingOwnerReasonEnumApi.LargestOwner]: 'your team owns the largest part of it',
    [RoutingOwnerReasonEnumApi.DiffNotSeen]: "the model could not read all of your team's changes",
    [RoutingOwnerReasonEnumApi.CutSkipped]: 'no model checked the change to narrow down the reviewers',
    [RoutingOwnerReasonEnumApi.ModelKept]: "the model judged your team's part worth a review",
    [RoutingOwnerReasonEnumApi.ModelCut]: "the model judged your team's part did not need a review",
    [RoutingOwnerReasonEnumApi.StamphogApproved]: 'stamphog approved it',
}

const WHY_BY_OUTCOME: Record<RoutingOwnerOutcomeEnumApi, (decision: StamphogRoutingRunOwnerApi) => string> = {
    [RoutingOwnerOutcomeEnumApi.Requested]: (decision) =>
        `Your team was asked because ${REASON_PHRASE[decision.reason]}.`,
    [RoutingOwnerOutcomeEnumApi.AlreadyRequested]: () =>
        'Your team was asked on an earlier commit of this pull request.',
    [RoutingOwnerOutcomeEnumApi.Labeled]: () =>
        'The pull request came from a fork, so your team got a label on it instead of a review request.',
    [RoutingOwnerOutcomeEnumApi.Refused]: () =>
        'Your team should have been asked, but GitHub refused the review request.',
    [RoutingOwnerOutcomeEnumApi.NotRequested]: (decision) =>
        decision.reason === RoutingOwnerReasonEnumApi.StamphogApproved
            ? 'Stamphog approved it, so your team was not asked.'
            : `Your team would have been asked because ${REASON_PHRASE[decision.reason]}, but stamphog approved it first.`,
    [RoutingOwnerOutcomeEnumApi.Cut]: () =>
        'Your part of the change was small, so a review from your team was not needed.',
}

export function whyTitle(outcome: RoutingOwnerOutcomeEnumApi): string {
    return isTeamAsked(outcome) ? 'Why your team was asked' : "Why your team wasn't asked"
}

export function whySentence(decision: StamphogRoutingRunOwnerApi): string {
    return WHY_BY_OUTCOME[decision.outcome](decision)
}
