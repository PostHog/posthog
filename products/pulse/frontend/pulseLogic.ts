import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import {
    subscriptionsCreate,
    subscriptionsList,
    subscriptionsPartialUpdate,
} from '@posthog/products-subscriptions/frontend/generated/api'
import {
    SubscriptionsListResourceType,
    type SubscriptionApi,
} from '@posthog/products-subscriptions/frontend/generated/api.schemas'

import { ApiError } from 'lib/api-error'
import { getDefaultSubscriptionStartDate, validateEmailTargetValue } from 'lib/components/Subscriptions/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import {
    pulseBriefsFeedbackCreate,
    pulseBriefsGenerateCreate,
    pulseBriefsList,
    pulseBriefsRetrieve,
    pulseBriefConfigsCreate,
    pulseBriefConfigsDestroy,
    pulseBriefConfigsList,
    pulseBriefConfigsPartialUpdate,
    pulseOpportunitiesActedCreate,
    pulseOpportunitiesDismissCreate,
    pulseOpportunitiesFeedbackCreate,
    pulseOpportunitiesList,
    pulseOpportunitiesReopenCreate,
    pulseOpportunitiesResearchCreate,
} from './generated/api'
import type {
    BriefConfigApi,
    InvestigationFindingApi,
    OpportunityApi,
    OpportunityApiEvidenceItem,
    ProductBriefApi,
    ProductBriefApiSectionsItem,
    ProductBriefListApi,
} from './generated/api.schemas'
import { OpportunityStatusEnumApi, ProductBriefStatusEnumApi } from './generated/api.schemas'
import type { pulseLogicType } from './pulseLogicType'

/** A `"type:ref"` evidence citation split into its parts, e.g. `insight:abc123`. */
export interface BriefCitation {
    type: string
    ref: string
}

/** Narrowed shape of one generated brief section — the API ships sections as untyped dicts. */
export interface BriefSection {
    kind: string
    title: string
    markdown: string
    citations: BriefCitation[]
    confidence: number
}

export function parseCitation(citation: string): BriefCitation {
    const separatorIndex = citation.indexOf(':')
    if (separatorIndex <= 0) {
        return { type: '', ref: citation }
    }
    return { type: citation.slice(0, separatorIndex), ref: citation.slice(separatorIndex + 1) }
}

/** A hallucinated ref must fall back to a plain tag, not a dead link. `Number('')` and `Number('0')`
 * are finite, so guard on `id > 0` — all resource ids are positive — to reject empty/zero refs too. */
function numericSceneUrl(ref: string, buildUrl: (id: number) => string): string | undefined {
    const id = Number(ref)
    return Number.isFinite(id) && id > 0 ? buildUrl(id) : undefined
}

/**
 * Citation types that link out, in one table so the tag label and its URL can't drift.
 * Unknown types render as plain tags. The backend source of truth for the linkable kinds is
 * `CandidateKind` in products/pulse/backend/generation/explain.py. Flags and experiments are
 * cited by numeric id (the scene route param); keys/names live in the candidate labels instead.
 */
export const CITATION_TYPES: Record<
    string,
    { label: string; url?: (ref: string) => string | undefined; hideRef?: boolean }
> = {
    insight: { label: 'Insight', url: (ref) => urls.insightView(ref as InsightShortId) },
    dashboard: { label: 'Dashboard', url: (ref) => urls.dashboard(ref) },
    flag: { label: 'Feature flag', url: (ref) => numericSceneUrl(ref, urls.featureFlag) },
    experiment: { label: 'Experiment', url: (ref) => numericSceneUrl(ref, (id) => urls.experiment(id)) },
    annotation: { label: 'Annotation', url: (ref) => numericSceneUrl(ref, urls.annotation) },
    // Accountability citations link to the scene's opportunities tab. Per-row anchors/highlights
    // were judged disproportionate for v1 — the panel is small enough to scan. hideRef: the
    // ref is an internal UUID, meaningless in a tag label.
    opportunity: { label: 'Opportunity', url: () => `${urls.pulse()}?tab=opportunities`, hideRef: true },
    // Investigation citations render as plain labeled tags — the "Query <n>" ref matches the
    // numbering in the goal-investigation card on the same page (anchor links were judged
    // disproportionate for v1).
    query: { label: 'Query' },
    // Replay-pattern findings cite the sessions behind them; the ref is a recording id linking
    // straight to the player. Session ids are opaque strings, so no numeric guard applies here.
    // hideRef: the ref is a full recording UUID, meaningless in a tag label.
    session: { label: 'Session', url: (ref) => urls.replaySingle(ref), hideRef: true },
}

export type PulseTab = 'briefs' | 'opportunities'

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

/** Evidence entries ship as untyped dicts — narrow them to citations, dropping malformed entries. */
export function parseOpportunityEvidence(evidence: readonly OpportunityApiEvidenceItem[]): BriefCitation[] {
    return evidence
        .map((entry) => ({
            type: typeof entry.type === 'string' ? entry.type : '',
            ref: typeof entry.ref === 'string' ? entry.ref : '',
        }))
        .filter((citation) => citation.ref !== '')
}

/** InvestigationFindingApi after defensive narrowing — `citations` (optional in the schema for
 * rows persisted before the field existed) is always present. */
export type InvestigationFinding = InvestigationFindingApi & { citations: string[] }

/** Defensive narrowing kept on top of the generated type: the findings live in a model-stored
 * JSON column, so runtime rows may predate or drift from the static shape. */
function parseInvestigationFinding(finding: InvestigationFindingApi): InvestigationFinding {
    return {
        question: typeof finding.question === 'string' ? finding.question : '',
        hogql: typeof finding.hogql === 'string' ? finding.hogql : '',
        result_summary: typeof finding.result_summary === 'string' ? finding.result_summary : '',
        succeeded: finding.succeeded === true,
        citations: Array.isArray(finding.citations)
            ? finding.citations.filter((citation): citation is string => typeof citation === 'string')
            : [],
    }
}

function parseSection(section: ProductBriefApiSectionsItem): BriefSection {
    return {
        kind: typeof section.kind === 'string' ? section.kind : '',
        title: typeof section.title === 'string' ? section.title : '',
        markdown: typeof section.markdown === 'string' ? section.markdown : '',
        citations: Array.isArray(section.citations)
            ? section.citations
                  .filter((citation): citation is string => typeof citation === 'string')
                  .map(parseCitation)
            : [],
        confidence: typeof section.confidence === 'number' ? section.confidence : 0,
    }
}

export const BRIEF_POLL_INTERVAL_MS = 3000

/** Stop polling and surface an error after this many consecutive rounds where every retrieve failed. */
export const MAX_CONSECUTIVE_POLL_FAILURES = 5

/** Research runs on a Temporal workflow (minutes); the opportunities list is polled until the
 * notebook appears. Bounded so a slow/failed run clears the spinner instead of spinning forever. */
export const RESEARCH_POLL_INTERVAL_MS = 5000
export const MAX_RESEARCH_POLL_ROUNDS = 90

/** First page only — deliberate for alpha; load-more is a follow-up. */
const LIST_PAGE_SIZE = 100

export const BRIEF_ALREADY_GENERATING_MESSAGE = 'A brief is already being generated'

// Cross-boundary contract: must match the ValidationError code raised by the generate endpoint
// in products/pulse/backend/api/brief.py — rename both sides together.
const AI_CONSENT_ERROR_CODE = 'ai_consent_required'

function currentProjectId(): string {
    return String(getCurrentTeamId())
}

function isAiConsentError(error: unknown): boolean {
    return error instanceof ApiError && error.code === AI_CONSENT_ERROR_CODE
}

function isGeneratingBrief(brief: ProductBriefListApi): boolean {
    return brief.status === ProductBriefStatusEnumApi.Generating
}

/** Once per brief per mount: the attention metric counts brief opens, not poll ticks or re-renders. */
function reportBriefViewed(cache: Record<string, any>, brief: ProductBriefApi | null | undefined): void {
    if (!brief || brief.status === ProductBriefStatusEnumApi.Generating) {
        return
    }
    cache.viewedBriefIds = cache.viewedBriefIds ?? new Set<string>()
    if (cache.viewedBriefIds.has(brief.id)) {
        return
    }
    cache.viewedBriefIds.add(brief.id)
    posthog.capture('product_brief_viewed', {
        brief_id: brief.id,
        status: brief.status,
        trigger: brief.trigger,
        period_days: brief.period_days,
        has_config: brief.config !== null,
    })
}

export interface BriefConfigForm {
    name: string
    focus_prompt: string
    dashboards: number[]
    goal: string
    // Insight short ID typed as plain text for v1 — no picker; validated server-side.
    goal_metric_short_id: string
}

const EMPTY_CONFIG_FORM: BriefConfigForm = {
    name: '',
    focus_prompt: '',
    dashboards: [],
    goal: '',
    goal_metric_short_id: '',
}

export type BriefScheduleFrequency = 'daily' | 'weekly'

export interface BriefScheduleForm {
    frequency: BriefScheduleFrequency
    // Comma-separated email addresses — same storage convention as the subscription form.
    target_value: string
}

const EMPTY_SCHEDULE_FORM: BriefScheduleForm = { frequency: 'weekly', target_value: '' }

export const pulseLogic = kea<pulseLogicType>([
    path(['products', 'pulse', 'frontend', 'pulseLogic']),
    connect(() => ({ values: [featureFlagLogic, ['featureFlags']] })),
    actions({
        setActiveTab: (tab: PulseTab) => ({ tab }),
        selectConfig: (configId: string | null) => ({ configId }),
        selectBrief: (briefId: string | null) => ({ briefId }),
        transitionOpportunity: (opportunityId: string, transition: OpportunityTransition) => ({
            opportunityId,
            transition,
        }),
        createExperimentFromOpportunity: (opportunityId: string) => ({ opportunityId }),
        researchOpportunity: (opportunityId: string) => ({ opportunityId }),
        researchStarted: (opportunityId: string) => ({ opportunityId }),
        researchRequested: (opportunity: OpportunityApi) => ({ opportunity }),
        researchFailed: (opportunityId: string) => ({ opportunityId }),
        researchCompleted: (opportunityId: string) => ({ opportunityId }),
        startResearchPolling: true,
        stopResearchPolling: true,
        pollResearchingOpportunities: true,
        opportunityTransitionStarted: (opportunityId: string, transition: OpportunityRowAction) => ({
            opportunityId,
            transition,
        }),
        opportunityTransitionSucceeded: (opportunity: OpportunityApi) => ({ opportunity }),
        opportunityTransitionFailed: (opportunityId: string) => ({ opportunityId }),
        voteOnBrief: (briefId: string, helpful: boolean | null) => ({ briefId, helpful }),
        voteOnOpportunity: (opportunityId: string, helpful: boolean | null) => ({ opportunityId, helpful }),
        feedbackVoteStarted: (targetId: string) => ({ targetId }),
        feedbackVoteSucceeded: (targetId: string) => ({ targetId }),
        feedbackVoteFailed: (targetId: string) => ({ targetId }),
        briefFeedbackUpdated: (brief: ProductBriefApi) => ({ brief }),
        opportunityFeedbackUpdated: (opportunity: OpportunityApi) => ({ opportunity }),
        setAiConsentRequired: (aiConsentRequired: boolean) => ({ aiConsentRequired }),
        startPolling: true,
        stopPolling: true,
        pollGeneratingBriefs: true,
        briefsRefreshed: (briefs: ProductBriefApi[]) => ({ briefs }),
        openConfigModal: (config: BriefConfigApi | null) => ({ config }),
        closeConfigModal: true,
        configSaved: (config: BriefConfigApi, created: boolean) => ({ config, created }),
        deleteConfig: (configId: string) => ({ configId }),
        configDeleted: (configId: string) => ({ configId }),
        configDeleteFailed: true,
        briefScheduled: (subscription: SubscriptionApi) => ({ subscription }),
        unscheduleBrief: (subscriptionId: number) => ({ subscriptionId }),
        briefUnscheduled: (subscriptionId: number) => ({ subscriptionId }),
        briefUnscheduleFailed: true,
    }),
    forms(({ actions, values }) => ({
        configForm: {
            defaults: EMPTY_CONFIG_FORM,
            errors: ({ name }: BriefConfigForm) => ({
                name: name.trim() ? undefined : 'Please enter a name',
            }),
            submit: async (formValues: BriefConfigForm) => {
                const editing = values.editingConfig
                // Only the dashboards anchor is editable here — spread the existing anchors so
                // insight anchors set through the API survive a save from this form.
                const anchors = { ...editing?.anchors, dashboards: formValues.dashboards }
                const goalMetricShortId = formValues.goal_metric_short_id.trim()
                const payload = {
                    name: formValues.name.trim(),
                    focus_prompt: formValues.focus_prompt,
                    anchors,
                    goal: formValues.goal.trim(),
                    goal_metric: goalMetricShortId ? { insight_short_id: goalMetricShortId } : null,
                }
                const saved = editing
                    ? await pulseBriefConfigsPartialUpdate(currentProjectId(), editing.id, payload)
                    : await pulseBriefConfigsCreate(currentProjectId(), payload)
                actions.configSaved(saved, !editing)
            },
        },
        scheduleForm: {
            defaults: EMPTY_SCHEDULE_FORM,
            errors: ({ target_value }: BriefScheduleForm) => ({
                target_value: validateEmailTargetValue(target_value),
            }),
            submit: async (formValues: BriefScheduleForm) => {
                const config = values.editingConfig
                if (!config) {
                    return // scheduling only exists for a saved config
                }
                const subscription = await subscriptionsCreate(currentProjectId(), {
                    pulse_brief_config_id: config.id,
                    title: `${config.name} brief`,
                    target_type: 'email',
                    target_value: formValues.target_value,
                    frequency: formValues.frequency,
                    interval: 1,
                    start_date: getDefaultSubscriptionStartDate(),
                })
                actions.briefScheduled(subscription)
            },
        },
    })),
    loaders(({ actions }) => ({
        briefConfigs: [
            [] as BriefConfigApi[],
            {
                loadBriefConfigs: async (): Promise<BriefConfigApi[]> => {
                    const response = await pulseBriefConfigsList(currentProjectId(), { limit: LIST_PAGE_SIZE })
                    return response.results
                },
            },
        ],
        briefs: [
            [] as ProductBriefListApi[],
            {
                loadBriefs: async (): Promise<ProductBriefListApi[]> => {
                    const response = await pulseBriefsList(currentProjectId(), { limit: LIST_PAGE_SIZE })
                    return response.results
                },
            },
        ],
        generatedBrief: [
            null as ProductBriefApi | null,
            {
                generateBrief: async ({ configId }: { configId: string | null }): Promise<ProductBriefApi | null> => {
                    try {
                        return await pulseBriefsGenerateCreate(currentProjectId(), { config_id: configId })
                    } catch (error) {
                        if (isAiConsentError(error)) {
                            // Handled with an in-scene banner — swallow so the global error toast stays quiet.
                            actions.setAiConsentRequired(true)
                            return null
                        }
                        throw error
                    }
                },
            },
        ],
        briefDetail: [
            null as ProductBriefApi | null,
            {
                loadBriefDetail: async ({ briefId }: { briefId: string }): Promise<ProductBriefApi> => {
                    return await pulseBriefsRetrieve(currentProjectId(), briefId)
                },
            },
        ],
        opportunities: [
            [] as OpportunityApi[],
            {
                loadOpportunities: async (): Promise<OpportunityApi[]> => {
                    const response = await pulseOpportunitiesList(currentProjectId(), { limit: LIST_PAGE_SIZE })
                    return response.results
                },
            },
        ],
        briefSubscriptions: [
            [] as SubscriptionApi[],
            {
                loadBriefSubscriptions: async (): Promise<SubscriptionApi[]> => {
                    const response = await subscriptionsList(currentProjectId(), {
                        resource_type: SubscriptionsListResourceType.PulseBrief,
                        limit: LIST_PAGE_SIZE,
                    })
                    return response.results
                },
            },
        ],
    })),
    reducers({
        activeTab: [
            'briefs' as PulseTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
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
        // Opportunities with a research run in flight — set optimistically on click so the button
        // spins immediately, cleared when the notebook lands (researchCompleted), the request fails
        // (researchFailed), or the poll gives up.
        researchInFlight: [
            {} as Record<string, true>,
            {
                researchStarted: (state, { opportunityId }) => ({ ...state, [opportunityId]: true as const }),
                researchFailed: (state, { opportunityId }) => {
                    const { [opportunityId]: _, ...rest } = state
                    return rest
                },
                researchCompleted: (state, { opportunityId }) => {
                    const { [opportunityId]: _, ...rest } = state
                    return rest
                },
            },
        ],
        // Keyed by brief/opportunity id (UUIDs — no cross-resource collision) so each vote
        // target guards independently.
        feedbackVotesInFlight: [
            {} as Record<string, true>,
            {
                feedbackVoteStarted: (state, { targetId }) => ({ ...state, [targetId]: true as const }),
                feedbackVoteSucceeded: (state, { targetId }) => {
                    const { [targetId]: _, ...rest } = state
                    return rest
                },
                feedbackVoteFailed: (state, { targetId }) => {
                    const { [targetId]: _, ...rest } = state
                    return rest
                },
            },
        ],
        selectedConfigId: [
            null as string | null,
            {
                selectConfig: (_, { configId }) => configId,
            },
        ],
        selectedBriefId: [
            null as string | null,
            {
                selectBrief: (_, { briefId }) => briefId,
            },
        ],
        aiConsentRequired: [
            false,
            {
                setAiConsentRequired: (_, { aiConsentRequired }) => aiConsentRequired,
                generateBrief: () => false,
            },
        ],
        configModalOpen: [
            false,
            {
                openConfigModal: () => true,
                closeConfigModal: () => false,
                configSaved: () => false,
            },
        ],
        editingConfig: [
            null as BriefConfigApi | null,
            {
                openConfigModal: (_, { config }) => config,
            },
        ],
        configIdBeingDeleted: [
            null as string | null,
            {
                deleteConfig: (_, { configId }) => configId,
                configDeleted: () => null,
                configDeleteFailed: () => null,
            },
        ],
        subscriptionIdBeingUnscheduled: [
            null as number | null,
            {
                unscheduleBrief: (_, { subscriptionId }) => subscriptionId,
                briefUnscheduled: () => null,
                briefUnscheduleFailed: () => null,
            },
        ],
        briefSubscriptions: {
            briefScheduled: (state, { subscription }) => [subscription, ...state],
            briefUnscheduled: (state, { subscriptionId }) =>
                state.filter((subscription) => subscription.id !== subscriptionId),
        },
        briefConfigs: {
            configSaved: (state, { config, created }) =>
                created ? [config, ...state] : state.map((existing) => (existing.id === config.id ? config : existing)),
            configDeleted: (state, { configId }) => state.filter((config) => config.id !== configId),
        },
        briefs: {
            generateBriefSuccess: (state, { generatedBrief }) => (generatedBrief ? [generatedBrief, ...state] : state),
            briefsRefreshed: (state, { briefs }) => {
                // Only swap in briefs whose status actually changed, so identities stay
                // stable across no-op poll ticks and derived selectors don't churn.
                const byId = new Map(briefs.map((brief) => [brief.id, brief]))
                let changed = false
                const next = state.map((brief) => {
                    const updated = byId.get(brief.id)
                    if (updated && updated.status !== brief.status) {
                        changed = true
                        return updated
                    }
                    return brief
                })
                return changed ? next : state
            },
        },
        briefDetail: {
            generateBriefSuccess: (state, { generatedBrief }) => generatedBrief ?? state,
            briefsRefreshed: (state, { briefs }) => {
                const updated = briefs.find((brief) => brief.id === state?.id)
                return updated && updated.status !== state?.status ? updated : state
            },
            // Server-confirmed swap only — no optimistic flip (same policy as opportunity rows).
            briefFeedbackUpdated: (state, { brief }) => (state?.id === brief.id ? brief : state),
        },
        opportunities: {
            // Server-confirmed swap only — the per-row spinner covers the wait, no optimistic flip.
            opportunityTransitionSucceeded: (state, { opportunity }) =>
                state.map((existing) => (existing.id === opportunity.id ? opportunity : existing)),
            opportunityFeedbackUpdated: (state, { opportunity }) =>
                state.map((existing) => (existing.id === opportunity.id ? opportunity : existing)),
            // Server-confirmed swap: the returned row carries the fresh research_requested_at.
            researchRequested: (state, { opportunity }) =>
                state.map((existing) => (existing.id === opportunity.id ? opportunity : existing)),
        },
    }),
    selectors({
        visibleBriefs: [
            (s) => [s.briefs, s.selectedConfigId],
            (briefs, selectedConfigId): ProductBriefListApi[] =>
                briefs.filter((brief) => brief.config === selectedConfigId),
        ],
        // Scoped to the selected focus: the backend locks generation per team+config, so a brief
        // generating for another config must not disable "Run brief now" for this one.
        isGeneratingForSelectedConfig: [
            (s) => [s.visibleBriefs, s.generatedBriefLoading],
            (visibleBriefs, generatedBriefLoading): boolean =>
                generatedBriefLoading || visibleBriefs.some(isGeneratingBrief),
        ],
        briefDetailSections: [
            (s) => [s.briefDetail],
            (briefDetail): BriefSection[] => (briefDetail?.sections ?? []).map(parseSection),
        ],
        // Findings of the shown brief, in citation order — a `query:<n>` citation is the
        // 1-based index into this list. Empty for goal-less briefs and list-shaped rows.
        briefDetailInvestigation: [
            (s) => [s.briefDetail],
            (briefDetail): InvestigationFinding[] => (briefDetail?.investigation ?? []).map(parseInvestigationFinding),
        ],
        // The goal of the config the shown brief was generated for — the subtle header line above
        // the brief detail. Null when the brief is config-less or its config has no goal.
        briefDetailGoal: [
            (s) => [s.briefDetail, s.briefConfigs],
            (briefDetail, briefConfigs): string | null => {
                if (!briefDetail?.config) {
                    return null
                }
                const goal = briefConfigs.find((config) => config.id === briefDetail.config)?.goal?.trim()
                return goal || null
            },
        ],
        // The subscription delivering the config being edited, if any — one schedule per config
        // is the v1 surface (more via the subscriptions page).
        editingConfigSubscription: [
            (s) => [s.briefSubscriptions, s.editingConfig],
            (briefSubscriptions, editingConfig): SubscriptionApi | null =>
                editingConfig
                    ? (briefSubscriptions.find(
                          (subscription) => subscription.pulse_brief_config_id === editingConfig.id
                      ) ?? null)
                    : null,
        ],
    }),
    listeners(({ actions, values, cache }) => {
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
        /** One vote round-trip, mirroring runTransition: in-flight guard, server call,
         * server-confirmed swap via onSuccess, toast on failure. */
        const runVote = async <T>(
            targetId: string,
            call: () => Promise<T>,
            onSuccess: (updated: T) => void
        ): Promise<void> => {
            if (targetId in values.feedbackVotesInFlight) {
                return // state-level double-submission guard; the buttons are also disabled
            }
            actions.feedbackVoteStarted(targetId)
            try {
                const updated = await call()
                actions.feedbackVoteSucceeded(targetId)
                onSuccess(updated)
            } catch (error) {
                actions.feedbackVoteFailed(targetId)
                lemonToast.error(
                    error instanceof ApiError && error.detail ? error.detail : 'Saving your feedback failed'
                )
            }
        }
        return {
            loadBriefsSuccess: ({ briefs }) => {
                if (values.selectedBriefId === null && values.visibleBriefs.length > 0) {
                    actions.selectBrief(values.visibleBriefs[0].id)
                }
                if (briefs.some(isGeneratingBrief)) {
                    actions.startPolling()
                }
            },
            selectConfig: () => {
                actions.selectBrief(values.visibleBriefs.length > 0 ? values.visibleBriefs[0].id : null)
            },
            selectBrief: ({ briefId }) => {
                if (briefId === null) {
                    return
                }
                if (values.briefDetail?.id !== briefId) {
                    actions.loadBriefDetail({ briefId })
                }
            },
            generateBriefSuccess: ({ generatedBrief }) => {
                if (!generatedBrief) {
                    return
                }
                actions.selectBrief(generatedBrief.id)
                actions.startPolling()
            },
            generateBriefFailure: ({ errorObject }) => {
                if (errorObject instanceof ApiError && errorObject.status === 409) {
                    lemonToast.info(BRIEF_ALREADY_GENERATING_MESSAGE)
                }
            },
            startPolling: () => {
                cache.pollFailureRounds = 0
                cache.disposables.add(() => {
                    const intervalId = setInterval(() => actions.pollGeneratingBriefs(), BRIEF_POLL_INTERVAL_MS)
                    return () => clearInterval(intervalId)
                }, 'briefPoll')
            },
            stopPolling: () => {
                cache.disposables.dispose('briefPoll')
            },
            pollGeneratingBriefs: async () => {
                // The single stop decision: a tick with nothing left to poll ends the interval.
                const generating = values.briefs.filter(isGeneratingBrief)
                if (generating.length === 0) {
                    actions.stopPolling()
                    return
                }
                if (cache.pollInFlight) {
                    return // A slow previous tick is still fetching — skip instead of stacking requests.
                }
                cache.pollInFlight = true
                try {
                    const results = await Promise.allSettled(
                        generating.map((brief) => pulseBriefsRetrieve(currentProjectId(), brief.id))
                    )
                    const refreshed = results
                        .filter(
                            (result): result is PromiseFulfilledResult<ProductBriefApi> => result.status === 'fulfilled'
                        )
                        .map((result) => result.value)
                    if (refreshed.length > 0) {
                        cache.pollFailureRounds = 0
                        actions.briefsRefreshed(refreshed)
                        return
                    }
                    // Every retrieve failed — count rounds so a persistent outage becomes legible instead
                    // of an interval spinning forever behind a "Generating…" state.
                    cache.pollFailureRounds = (cache.pollFailureRounds ?? 0) + 1
                    if (cache.pollFailureRounds >= MAX_CONSECUTIVE_POLL_FAILURES) {
                        actions.stopPolling()
                        lemonToast.error('Checking brief status keeps failing — reload the page to retry')
                    }
                } finally {
                    cache.pollInFlight = false
                }
            },
            openConfigModal: ({ config }) => {
                actions.resetConfigForm({
                    name: config?.name ?? '',
                    focus_prompt: config?.focus_prompt ?? '',
                    dashboards: config?.anchors?.dashboards ?? [],
                    goal: config?.goal ?? '',
                    goal_metric_short_id: config?.goal_metric?.insight_short_id ?? '',
                })
                actions.resetScheduleForm(EMPTY_SCHEDULE_FORM)
            },
            briefScheduled: () => {
                lemonToast.success('Brief scheduled')
            },
            submitScheduleFormFailure: ({ error }) => {
                // Field-level validation failures already render inline — only toast API errors.
                if (error instanceof ApiError) {
                    lemonToast.error(error.detail || 'Scheduling the brief failed')
                }
            },
            unscheduleBrief: async ({ subscriptionId }) => {
                try {
                    // Subscriptions forbid hard deletes — soft-delete via PATCH.
                    await subscriptionsPartialUpdate(currentProjectId(), subscriptionId, { deleted: true })
                } catch {
                    actions.briefUnscheduleFailed()
                    lemonToast.error('Removing the schedule failed')
                    return
                }
                actions.briefUnscheduled(subscriptionId)
                lemonToast.success('Brief schedule removed')
            },
            configSaved: ({ config, created }) => {
                lemonToast.success(created ? 'Brief config created' : 'Brief config updated')
                if (created) {
                    actions.selectConfig(config.id)
                }
            },
            submitConfigFormFailure: ({ error }) => {
                // Field-level validation failures already render inline — only toast API errors.
                if (error instanceof ApiError) {
                    lemonToast.error(error.detail || 'Saving the brief config failed')
                }
            },
            transitionOpportunity: async ({ opportunityId, transition }) => {
                await runTransition(opportunityId, transition, OPPORTUNITY_TRANSITIONS[transition].call)
            },
            voteOnBrief: async ({ briefId, helpful }) => {
                await runVote(
                    briefId,
                    () => pulseBriefsFeedbackCreate(currentProjectId(), briefId, { helpful }),
                    actions.briefFeedbackUpdated
                )
            },
            voteOnOpportunity: async ({ opportunityId, helpful }) => {
                await runVote(
                    opportunityId,
                    () => pulseOpportunitiesFeedbackCreate(currentProjectId(), opportunityId, { helpful }),
                    actions.opportunityFeedbackUpdated
                )
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
                // metric param; hypothesis and flag key have no params — a prefill hook is the
                // recorded ask), so the proposal travels via clipboard for the blank form.
                const copied = await copyToClipboard(
                    [
                        `Hypothesis: ${proposal.hypothesis}`,
                        `Feature flag key: ${proposal.flag_key_suggestion}`,
                        ...(proposal.target_metric
                            ? [`Target metric insight: ${proposal.target_metric.insight_short_id}`]
                            : []),
                        `Variants: ${proposal.variant_sketch}`,
                    ].join('\n'),
                    'experiment proposal'
                )
                if (!copied) {
                    // Still navigate — the proposal stays visible on the opportunity row.
                    lemonToast.warning('Could not copy the proposal — find it on the opportunity row')
                }
                router.actions.push(urls.experiment('new'))
            },
            researchOpportunity: async ({ opportunityId }) => {
                if (opportunityId in values.researchInFlight) {
                    return // state-level double-submission guard; the button is also disabled
                }
                // Optimistic spinner: the run is a Temporal workflow, so the button reflects intent
                // immediately and the poll below swaps in the notebook link when it lands.
                actions.researchStarted(opportunityId)
                try {
                    const updated = await pulseOpportunitiesResearchCreate(currentProjectId(), opportunityId)
                    actions.researchRequested(updated)
                    actions.startResearchPolling()
                } catch (error) {
                    actions.researchFailed(opportunityId)
                    if (isAiConsentError(error)) {
                        actions.setAiConsentRequired(true)
                        return
                    }
                    if (error instanceof ApiError && error.status === 429) {
                        lemonToast.info('Daily research limit reached for this team — try again later')
                        return
                    }
                    if (error instanceof ApiError && error.status === 409) {
                        lemonToast.info('Research is already running for this opportunity')
                        return
                    }
                    lemonToast.error(
                        error instanceof ApiError && error.detail ? error.detail : 'Starting research failed'
                    )
                }
            },
            startResearchPolling: () => {
                cache.researchPollRounds = 0
                cache.disposables.add(() => {
                    const intervalId = setInterval(
                        () => actions.pollResearchingOpportunities(),
                        RESEARCH_POLL_INTERVAL_MS
                    )
                    return () => clearInterval(intervalId)
                }, 'researchPoll')
            },
            stopResearchPolling: () => {
                cache.disposables.dispose('researchPoll')
            },
            pollResearchingOpportunities: () => {
                if (Object.keys(values.researchInFlight).length === 0) {
                    actions.stopResearchPolling()
                    return
                }
                if ((cache.researchPollRounds ?? 0) >= MAX_RESEARCH_POLL_ROUNDS) {
                    // Give up the spinner (the notebook may still land — a reload will show it) so a
                    // slow or failed run doesn't spin forever.
                    actions.stopResearchPolling()
                    Object.keys(values.researchInFlight).forEach((id) => actions.researchFailed(id))
                    lemonToast.info('Research is taking a while — reload to check for the notebook')
                    return
                }
                if (values.opportunitiesLoading) {
                    return // a slow previous refresh is still running — skip instead of stacking
                }
                cache.researchPollRounds = (cache.researchPollRounds ?? 0) + 1
                actions.loadOpportunities()
            },
            setActiveTab: ({ tab }) => {
                // Lazy first load — briefs are the default landing surface, so the opportunities
                // request waits until the tab is actually opened. The flag only latches on success,
                // so a failed load retries on the next switch instead of masquerading as empty.
                if (
                    tab === 'opportunities' &&
                    !cache.opportunitiesLoaded &&
                    !values.opportunitiesLoading &&
                    values.featureFlags[FEATURE_FLAGS.PULSE]
                ) {
                    actions.loadOpportunities()
                }
            },
            loadOpportunitiesSuccess: ({ opportunities }) => {
                cache.opportunitiesLoaded = true
                // Clear the research spinner for any opportunity whose notebook has now landed.
                for (const opportunityId of Object.keys(values.researchInFlight)) {
                    const fresh = opportunities.find((opportunity) => opportunity.id === opportunityId)
                    if (fresh?.research_notebook_short_id) {
                        actions.researchCompleted(opportunityId)
                    }
                }
            },
            loadOpportunitiesFailure: () => {
                lemonToast.error('Loading opportunities failed — reopen the tab to retry')
            },
            loadBriefDetailSuccess: ({ briefDetail }) => {
                reportBriefViewed(cache, briefDetail)
            },
            briefsRefreshed: () => {
                // The poll path swaps a generating detail to terminal without a loadBriefDetail.
                reportBriefViewed(cache, values.briefDetail)
            },
            deleteConfig: async ({ configId }) => {
                try {
                    await pulseBriefConfigsDestroy(currentProjectId(), configId)
                } catch {
                    actions.configDeleteFailed()
                    lemonToast.error('Deleting the brief config failed')
                    return
                }
                if (values.selectedConfigId === configId) {
                    actions.selectConfig(null)
                }
                actions.configDeleted(configId)
                lemonToast.success('Brief config deleted')
            },
        }
    }),
    actionToUrl(({ values }) => ({
        setActiveTab: () => [
            router.values.location.pathname,
            { ...router.values.searchParams, tab: values.activeTab === 'briefs' ? undefined : values.activeTab },
        ],
    })),
    urlToAction(({ actions, values }) => ({
        [urls.pulse()]: (_, searchParams) => {
            const tab: PulseTab = searchParams.tab === 'opportunities' ? 'opportunities' : 'briefs'
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        // The scene renders NotFound without the flag — don't fire the pulse API calls either.
        if (!values.featureFlags[FEATURE_FLAGS.PULSE]) {
            return
        }
        actions.loadBriefConfigs()
        actions.loadBriefs()
        actions.loadBriefSubscriptions()
    }),
])
