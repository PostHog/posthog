import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    pulseOpportunitiesActedCreate,
    pulseOpportunitiesDismissCreate,
    pulseOpportunitiesList,
    pulseOpportunitiesReopenCreate,
} from './generated/api'
import type { OpportunityApi } from './generated/api.schemas'
import { OpportunityStatusEnumApi } from './generated/api.schemas'
import type { opportunitiesLogicType } from './opportunitiesLogicType'
import { currentProjectId, LIST_PAGE_SIZE } from './utils'

export type OpportunityTransition = 'dismiss' | 'acted' | 'reopen'

/** The lifecycle transitions in one table so endpoint, allowed source status, and button label can't drift. */
export const OPPORTUNITY_TRANSITIONS: Record<
    OpportunityTransition,
    {
        call: (projectId: string, id: string) => Promise<OpportunityApi>
        from: OpportunityStatusEnumApi
        label: string
    }
> = {
    // Key order is button order for statuses offering several transitions.
    acted: { call: pulseOpportunitiesActedCreate, from: OpportunityStatusEnumApi.Open, label: 'Mark as acted' },
    dismiss: { call: pulseOpportunitiesDismissCreate, from: OpportunityStatusEnumApi.Open, label: 'Dismiss' },
    reopen: { call: pulseOpportunitiesReopenCreate, from: OpportunityStatusEnumApi.Dismissed, label: 'Reopen' },
}

/** The row actions a status offers, derived from the transition table. */
export function transitionsForStatus(
    status: OpportunityStatusEnumApi
): { transition: OpportunityTransition; label: string }[] {
    return (Object.keys(OPPORTUNITY_TRANSITIONS) as OpportunityTransition[])
        .filter((transition) => OPPORTUNITY_TRANSITIONS[transition].from === status)
        .map((transition) => ({ transition, label: OPPORTUNITY_TRANSITIONS[transition].label }))
}

export const opportunitiesLogic = kea<opportunitiesLogicType>([
    path(['products', 'pulse', 'frontend', 'opportunitiesLogic']),
    connect(() => ({ values: [featureFlagLogic, ['featureFlags']] })),
    actions({
        transitionOpportunity: (opportunityId: string, transition: OpportunityTransition) => ({
            opportunityId,
            transition,
        }),
        opportunityTransitionStarted: (opportunityId: string, transition: OpportunityTransition) => ({
            opportunityId,
            transition,
        }),
        opportunityTransitionSucceeded: (opportunity: OpportunityApi) => ({ opportunity }),
        opportunityTransitionFailed: (opportunityId: string) => ({ opportunityId }),
    }),
    loaders({
        opportunities: [
            [] as OpportunityApi[],
            {
                loadOpportunities: async (): Promise<OpportunityApi[]> => {
                    const response = await pulseOpportunitiesList(currentProjectId(), { limit: LIST_PAGE_SIZE })
                    return response.results
                },
            },
        ],
    }),
    reducers({
        opportunities: {
            // Server-confirmed swap only — the per-row spinner covers the wait, no optimistic flip.
            opportunityTransitionSucceeded: (state, { opportunity }) =>
                state.map((existing) => (existing.id === opportunity.id ? opportunity : existing)),
        },
        // Keyed by opportunity id so each row's buttons can spinner/disable independently.
        transitionsInFlight: [
            {} as Record<string, OpportunityTransition>,
            {
                opportunityTransitionStarted: (state, { opportunityId, transition }) => ({
                    ...state,
                    [opportunityId]: transition,
                }),
                opportunityTransitionSucceeded: (state, { opportunity }) => {
                    const { [opportunity.id]: _, ...rest } = state
                    return rest
                },
                opportunityTransitionFailed: (state, { opportunityId }) => {
                    const { [opportunityId]: _, ...rest } = state
                    return rest
                },
            },
        ],
        // A failed load must render an error with a retry, not the "run a brief" empty state alongside a toast.
        opportunitiesLoadFailed: [
            false,
            {
                loadOpportunities: () => false,
                loadOpportunitiesSuccess: () => false,
                loadOpportunitiesFailure: () => true,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        transitionOpportunity: async ({ opportunityId, transition }) => {
            if (opportunityId in values.transitionsInFlight) {
                return // state-level double-submission guard; the row's buttons are also disabled
            }
            actions.opportunityTransitionStarted(opportunityId, transition)
            try {
                const updated = await OPPORTUNITY_TRANSITIONS[transition].call(currentProjectId(), opportunityId)
                actions.opportunityTransitionSucceeded(updated)
            } catch (error) {
                actions.opportunityTransitionFailed(opportunityId)
                lemonToast.error(
                    error instanceof ApiError && error.detail ? error.detail : 'Updating the opportunity failed'
                )
            }
        },
        loadOpportunitiesFailure: () => {
            lemonToast.error('Loading opportunities failed')
        },
    })),
    afterMount(({ actions, values }) => {
        // The scene renders NotFound without the flag — don't fire the pulse API calls either.
        if (!values.featureFlags[FEATURE_FLAGS.PULSE]) {
            return
        }
        actions.loadOpportunities()
    }),
])
