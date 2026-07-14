import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

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

/** What a row can have in flight: a plain lifecycle transition, or the create-experiment flow
 * (an acted transition followed by a navigation) — distinct so only its own button spinners. */
export type OpportunityRowAction = OpportunityTransition | 'create_experiment'

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
        createExperimentFromOpportunity: (opportunityId: string) => ({ opportunityId }),
        opportunityTransitionStarted: (opportunityId: string, transition: OpportunityRowAction) => ({
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
            {} as Record<string, OpportunityRowAction>,
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
    listeners(({ actions, values }) => {
        /** One transition round-trip: in-flight guard, server call, row swap on success, toast on
         * failure. Returns the updated row, or null when skipped or failed. */
        const runTransition = async (
            opportunityId: string,
            action: OpportunityRowAction,
            call: (projectId: string, id: string) => Promise<OpportunityApi>
        ): Promise<OpportunityApi | null> => {
            if (opportunityId in values.transitionsInFlight) {
                return null // state-level double-submission guard; the row's buttons are also disabled
            }
            actions.opportunityTransitionStarted(opportunityId, action)
            try {
                const updated = await call(currentProjectId(), opportunityId)
                actions.opportunityTransitionSucceeded(updated)
                return updated
            } catch (error) {
                actions.opportunityTransitionFailed(opportunityId)
                lemonToast.error(
                    error instanceof ApiError && error.detail ? error.detail : 'Updating the opportunity failed'
                )
                return null
            }
        }
        return {
            transitionOpportunity: async ({ opportunityId, transition }) => {
                await runTransition(opportunityId, transition, OPPORTUNITY_TRANSITIONS[transition].call)
            },
            createExperimentFromOpportunity: async ({ opportunityId }) => {
                const proposal = values.opportunities.find((o) => o.id === opportunityId)?.proposed_experiment
                if (!proposal) {
                    return // the button only renders with a proposal; a stale click is a no-op
                }
                // The acted transition lands FIRST so accountability re-scores this opportunity even
                // if the user abandons the experiment form after navigation. A skipped or failed
                // transition never leaves the scene.
                const updated = await runTransition(
                    opportunityId,
                    'create_experiment',
                    OPPORTUNITY_TRANSITIONS.acted.call
                )
                if (!updated) {
                    return
                }
                // The experiments creation URL prefills nothing usable today (name is gated behind a
                // metric param; hypothesis and flag key have no params), so the proposal travels via
                // clipboard for the blank form. One predicate for clipboard, telemetry, and the row
                // summary, so an empty short_id (type-permitted, backend never emits it) can't diverge.
                const hasTargetMetric = !!proposal.target_metric?.insight_short_id
                const copied = await copyToClipboard(
                    [
                        `Hypothesis: ${proposal.hypothesis}`,
                        `Feature flag key: ${proposal.flag_key_suggestion}`,
                        ...(hasTargetMetric
                            ? [`Target metric insight: ${proposal.target_metric!.insight_short_id}`]
                            : []),
                        `Variants: ${proposal.variant_sketch}`,
                    ].join('\n'),
                    'experiment proposal'
                )
                if (!copied) {
                    // Still navigate — the proposal stays visible on the opportunity row.
                    lemonToast.warning('Could not copy the proposal — find it on the opportunity row')
                }
                // Measures the proposal→experiment funnel: which proposals get acted on, and whether
                // the clipboard handoff (the only bridge to the blank form) actually landed.
                posthog.capture('pulse_opportunity_experiment_created', {
                    opportunity_id: opportunityId,
                    has_target_metric: hasTargetMetric,
                    proposal_copied: copied,
                })
                router.actions.push(urls.experiment('new'))
            },
            loadOpportunitiesFailure: () => {
                lemonToast.error('Loading opportunities failed')
            },
        }
    }),
    afterMount(({ actions, values }) => {
        // The scene renders NotFound without the flag — don't fire the pulse API calls either.
        if (!values.featureFlags[FEATURE_FLAGS.PULSE]) {
            return
        }
        actions.loadOpportunities()
    }),
])
