import {
    RoutingOwnerOutcomeEnumApi,
    RoutingOwnerReasonEnumApi,
    StamphogRoutingRunApi,
    StamphogRoutingRunOwnerApi,
    StamphogRoutingRunsListOutcomeItem,
} from '../../generated/api.schemas'

/** The owner outcomes the team view filters on. The other outcomes are rare and stay in the runs API. */
export type TeamViewOutcome =
    | typeof StamphogRoutingRunsListOutcomeItem.NotRequested
    | typeof StamphogRoutingRunsListOutcomeItem.Cut
    | typeof StamphogRoutingRunsListOutcomeItem.Requested

const SEGMENT_LABEL: Record<TeamViewOutcome, string> = {
    [StamphogRoutingRunsListOutcomeItem.NotRequested]: 'Would have been asked',
    [StamphogRoutingRunsListOutcomeItem.Cut]: 'Cut by the model',
    [StamphogRoutingRunsListOutcomeItem.Requested]: 'Asked',
}

export const TEAM_VIEW_OUTCOME_OPTIONS: { value: TeamViewOutcome; label: string }[] = [
    {
        value: StamphogRoutingRunsListOutcomeItem.NotRequested,
        label: SEGMENT_LABEL[StamphogRoutingRunsListOutcomeItem.NotRequested],
    },
    { value: StamphogRoutingRunsListOutcomeItem.Cut, label: SEGMENT_LABEL[StamphogRoutingRunsListOutcomeItem.Cut] },
    {
        value: StamphogRoutingRunsListOutcomeItem.Requested,
        label: SEGMENT_LABEL[StamphogRoutingRunsListOutcomeItem.Requested],
    },
]

export const DEFAULT_OUTCOME: TeamViewOutcome = StamphogRoutingRunsListOutcomeItem.NotRequested

/**
 * The outcomes that mean the team was asked. Besides `requested`, the team was asked on an earlier run
 * (`already_requested`) or by label on a fork pull request (`labeled`), so no pull request drops out of the "Asked" tab.
 */
export const ASKED_OUTCOMES: StamphogRoutingRunsListOutcomeItem[] = [
    StamphogRoutingRunsListOutcomeItem.Requested,
    StamphogRoutingRunsListOutcomeItem.AlreadyRequested,
    StamphogRoutingRunsListOutcomeItem.Labeled,
]

export type TeamViewWindowDays = 7 | 30 | 90

export const TEAM_VIEW_WINDOW_OPTIONS: { value: TeamViewWindowDays; label: string }[] = [
    { value: 7, label: 'Last 7 days' },
    { value: 30, label: 'Last 30 days' },
    { value: 90, label: 'Last 90 days' },
]

export const DEFAULT_WINDOW_DAYS: TeamViewWindowDays = 7

const REASON_LABEL: Record<RoutingOwnerReasonEnumApi, string> = {
    [RoutingOwnerReasonEnumApi.Sensitive]: 'Owns a sensitive path',
    [RoutingOwnerReasonEnumApi.NewPath]: 'Owns a new path',
    [RoutingOwnerReasonEnumApi.LargestOwner]: 'Owns the largest part',
    [RoutingOwnerReasonEnumApi.DiffNotSeen]: 'Model did not see the whole diff',
    [RoutingOwnerReasonEnumApi.CutSkipped]: 'No model call',
    [RoutingOwnerReasonEnumApi.ModelKept]: 'Kept by the model',
    [RoutingOwnerReasonEnumApi.ModelCut]: 'Cut by the model',
    [RoutingOwnerReasonEnumApi.StamphogApproved]: 'Stamphog approved',
}

const OUTCOME_LABEL: Record<RoutingOwnerOutcomeEnumApi, string> = {
    [RoutingOwnerOutcomeEnumApi.Requested]: SEGMENT_LABEL[StamphogRoutingRunsListOutcomeItem.Requested],
    [RoutingOwnerOutcomeEnumApi.Labeled]: 'Labeled',
    [RoutingOwnerOutcomeEnumApi.Refused]: 'Refused by GitHub',
    [RoutingOwnerOutcomeEnumApi.Cut]: SEGMENT_LABEL[StamphogRoutingRunsListOutcomeItem.Cut],
    [RoutingOwnerOutcomeEnumApi.NotRequested]: SEGMENT_LABEL[StamphogRoutingRunsListOutcomeItem.NotRequested],
    [RoutingOwnerOutcomeEnumApi.AlreadyRequested]: 'Asked earlier',
}

export function outcomeLabel(outcome: RoutingOwnerOutcomeEnumApi): string {
    return OUTCOME_LABEL[outcome] ?? outcome
}

export function reasonLabel(reason: RoutingOwnerReasonEnumApi): string {
    return REASON_LABEL[reason] ?? reason
}

/** The run's decision about one owner, or null when the owner was not a candidate in this run. */
export function ownerDecision(run: StamphogRoutingRunApi, owner: string): StamphogRoutingRunOwnerApi | null {
    return run.owners.find((entry) => entry.owner === owner) ?? null
}
