import { MakeLogicType, actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import type { SkillPickerGroup } from 'lib/components/SkillPicker/SkillPicker'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/posthog_ai/frontend/types/taskTypes'
import {
    reviewHogBlindSpotsList,
    reviewHogBlindSpotsPartialUpdate,
    reviewHogPerspectivesList,
    reviewHogPerspectivesPartialUpdate,
    reviewHogResolutionList,
    reviewHogResolutionPartialUpdate,
    reviewHogReviewsPerspectiveStatsRetrieve,
    reviewHogReviewsRetrieve,
    reviewHogReviewsTableRetrieve,
    reviewHogReviewsTriggerCreate,
    reviewHogSettingsPartialUpdate,
    reviewHogSettingsRetrieve,
    reviewHogValidatorsList,
    reviewHogValidatorsPartialUpdate,
} from 'products/review_hog/frontend/generated/api'
import type {
    PatchedReviewUserSettingsApi,
    ReviewBlindSpotsConfigApi,
    ReviewDetailApi,
    ReviewFindingApi,
    ReviewIssuePriorityEnumApi,
    ReviewPerspectiveConfigApi,
    ReviewPerspectiveStatItemApi,
    ReviewPerspectiveStatsApi,
    ReviewRecentReviewApi,
    ReviewResolutionConfigApi,
    ReviewReviewsTablePageApi,
    ReviewUserSettingsApi,
    ReviewValidatorConfigApi,
} from 'products/review_hog/frontend/generated/api.schemas'
import {
    ReviewHogReviewsListScope,
    ReviewHogReviewsPerspectiveStatsRetrieveScope,
    ReviewHogReviewsTableRetrieveReviewMode,
    ReviewHogReviewsTableRetrieveStatus,
    ReviewTriggerRequestRunModeEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'
import { llmSkillsList, llmSkillsNameDuplicateCreate } from 'products/skills/frontend/generated/api'
import type { LLMSkillListApi } from 'products/skills/frontend/generated/api.schemas'

export type ReviewSkillKind = 'perspective' | 'blind_spots' | 'validator' | 'resolution'

export type ReviewDrawerTab =
    | 'published'
    | 'not_posted'
    | 'below_threshold'
    | 'dismissed'
    | 'chunks'
    | 'how_it_ran'
    | 'review'

export type CodeReviewTab = 'activity' | 'settings'

/** The personal preferences that fall back to a project default when the user has no own value. */
export type ProjectDefaultKey = 'urgency_threshold' | 'celebrate_clean_reviews'

export const REVIEW_PRIORITY_RANK: Record<ReviewIssuePriorityEnumApi, number> = {
    consider: 0,
    should_fix: 1,
    must_fix: 2,
}

// Poll cadence while the visible page has a running review, so its stage label stays live.
const IN_PROGRESS_POLL_INTERVAL_MS = 10_000

/** What the poll remembers about a row between responses, to spot a run finishing. */
interface ReviewRunMarker {
    inProgress: boolean
    runCount: number
}

// How long after triggering a review the list keeps polling for its report row to appear — the row
// is created seconds after the 202 by the workflow's fetch step, but a run that dies before creating
// it must not keep the list polling forever.
const TRIGGERED_REVIEW_WATCH_TIMEOUT_MS = 2 * 60 * 1000

export const REVIEWS_PAGE_SIZE = 25

/** The detail's valid findings split by the user's urgency threshold: on the PR vs. kept back. */
export interface ReviewFindingsSplit {
    published: ReviewFindingApi[]
    belowThreshold: ReviewFindingApi[]
}

/** How many surviving findings each review skill contributed, largest contributor first. */
export interface PerspectiveScore {
    skillName: string
    count: number
}

// Mirrors the backend naming contract (skill_loader.py): the name prefix is a review skill's whole
// identity, so an adopted copy must be created under its kind's prefix to be discovered by runs.
export const REVIEW_SKILL_PREFIX_BY_KIND: Record<ReviewSkillKind, string> = {
    perspective: 'review-hog-perspective-',
    blind_spots: 'review-hog-blind-spots-',
    validator: 'review-hog-validation-',
    resolution: 'review-hog-resolution-',
}

export const REVIEW_SKILL_KIND_LABELS: Record<ReviewSkillKind, string> = {
    perspective: 'perspective',
    blind_spots: 'blind-spot check',
    validator: 'validation criteria',
    resolution: 'resolution criteria',
}

// Group headings for the adopt picker: teammates' ready-made skills of the kind first (invisible in
// the cards above, since customs are author-only there), then the rest of the team's skill store.
const ADOPT_TEAMMATE_GROUP_LABELS: Record<ReviewSkillKind, string> = {
    perspective: 'Perspectives from your teammates',
    blind_spots: 'Blind-spot checks from your teammates',
    validator: 'Validation criteria from your teammates',
    resolution: 'Resolution criteria from your teammates',
}

/** Mirrors the skills API name limit: the whole adopted name (prefix + slug) must fit. */
export const SKILL_NAME_MAX_LENGTH = 64

// Page size for loading the skill store; the loader follows the pagination to the end, so this
// only bounds how many requests a large store takes, never which skills the picker offers.
const ADOPTABLE_SKILLS_PAGE_SIZE = 300

/** The existing skill an adoption copies from. */
export interface AdoptSource {
    name: string
    description: string
}

/** Prefill slug for an adopted copy: the source name minus any review-hog kind prefix, cut to fit. */
export function defaultAdoptSlug(sourceName: string, kind: ReviewSkillKind): string {
    const knownPrefix = Object.values(REVIEW_SKILL_PREFIX_BY_KIND).find((prefix) => sourceName.startsWith(prefix))
    const bare = knownPrefix ? sourceName.slice(knownPrefix.length) : sourceName
    const maxSlugLength = SKILL_NAME_MAX_LENGTH - REVIEW_SKILL_PREFIX_BY_KIND[kind].length
    return bare.slice(0, maxSlugLength).replace(/-+$/, '')
}

/** Client-side mirror of the skills API name rules, so the confirm step can reject inline. */
export function validateAdoptSlug(slug: string, kind: ReviewSkillKind, takenNames: Set<string>): string | null {
    if (!slug) {
        return 'Enter a name for the copy'
    }
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) {
        return 'Use lowercase letters, numbers, and single hyphens between words'
    }
    const fullName = REVIEW_SKILL_PREFIX_BY_KIND[kind] + slug
    if (fullName.length > SKILL_NAME_MAX_LENGTH) {
        return `The full name must be ${SKILL_NAME_MAX_LENGTH} characters or fewer`
    }
    if (takenNames.has(fullName)) {
        return 'A skill with this name already exists'
    }
    return null
}

// Thin scout-style kickoff pointers (mirrors SCOUT_AUTHOR_PROMPT): the actual authoring guide —
// pipeline context, naming contract, per-kind body shape, activation steps — lives in the
// `review-hog-authoring` team skill (canonical source: products/review_hog/skills/), synced per
// team like the perspectives. Keep knowledge there, not here.
const SKILL_AUTHOR_TASKS: Record<ReviewSkillKind, { title: string; prompt: string }> = {
    perspective: {
        title: 'Create a PostHog Review perspective',
        prompt: `I'd like to create a custom review perspective for PostHog Review in this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it. Follow its review-perspective path.

Ground yourself per that skill first, then ask me what my perspective should focus on and offer a few concrete directions the current set doesn't already cover. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: list the team's review-hog-perspective-* skills and read a canonical one to learn the shape before authoring.`,
    },
    blind_spots: {
        title: 'Create a PostHog Review blind-spot check',
        prompt: `I'd like to create a custom PostHog Review blind-spot check for this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it. Follow its blind-spot-check path.

Ground yourself per that skill first, then ask me what my sweep should emphasize and offer a few concrete directions. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: read the canonical review-hog-blind-spots-general skill to learn the shape before authoring.`,
    },
    validator: {
        title: 'Create PostHog Review validation criteria',
        prompt: `I'd like to create custom PostHog Review validation criteria for this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it. Follow its validation-criteria path.

Ground yourself per that skill first, then ask me how my bar should differ (stricter, more lenient, or weighted toward specific concerns) and offer a few concrete directions. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: read the canonical review-hog-validation-criteria skill to learn the shape before authoring.`,
    },
    resolution: {
        title: 'Create PostHog Review resolution criteria',
        prompt: `I'd like to create custom PostHog Review resolution criteria for this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it. Follow its resolution-criteria path.

Ground yourself per that skill first, then ask me how my bar for implementing review-thread asks should differ (more conservative, more eager, or weighted toward specific kinds of fixes) and offer a few concrete directions. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: read the canonical review-hog-resolution-criteria skill to learn the shape before authoring.`,
    },
}

function currentProjectId(): string {
    return String(teamLogic.values.currentTeamId)
}

/** "https://github.com/Org/Repo/pull/123/files" → "org/repo/123"; null when not a PR URL. */
function parsePrPath(url: string): string | null {
    const match = url
        .trim()
        .toLowerCase()
        .match(/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/)
    return match ? `${match[1]}/${match[2]}/${match[3]}` : null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reviewHogSettingsLogicValues {
    activeTab: CodeReviewTab
    adoptNewSkillName: string
    adoptSkillGroups: SkillPickerGroup[]
    adoptSkillKind: ReviewSkillKind | null
    adoptSlug: string
    adoptSlugError: string | null
    adoptSource: AdoptSource | null
    adoptableSkills: LLMSkillListApi[] | null
    adoptableSkillsLoading: boolean
    adoptingSkill: boolean
    awaitingTriggeredReview: boolean
    blindSpots: ReviewBlindSpotsConfigApi[] | null
    blindSpotsLoading: boolean
    creatingSkillKind: ReviewSkillKind | null
    deepSkillKept: Record<string, ReviewPerspectiveStatItemApi> | null
    deepSkillStats: ReviewPerspectiveStatsApi | null
    deepSkillStatsLoading: boolean
    deepValidationKept: {
        judged: number
        kept: number
    } | null
    hasUserChosenReviewsScope: boolean
    initialLoadFailed: boolean
    openedReview: ReviewRecentReviewApi | null
    openedReviewId: string | null
    perspectiveScoreboard: PerspectiveScore[] | null
    perspectiveStats: ReviewPerspectiveStatsApi | null
    perspectiveStatsLoading: boolean
    perspectives: ReviewPerspectiveConfigApi[] | null
    perspectivesLoading: boolean
    pipelineDetailOpen: boolean
    resolutionSkills: ReviewResolutionConfigApi[] | null
    resolutionSkillsLoading: boolean
    reviewDetail: ReviewDetailApi | null
    reviewDetailLoading: boolean
    reviewDrawerOpen: boolean
    reviewDrawerTab: ReviewDrawerTab
    reviewFindingsSplit: ReviewFindingsSplit | null
    reviews: ReviewRecentReviewApi[] | null
    reviewsCurrentPage: number
    reviewsFailed: boolean
    reviewsFiltered: boolean
    reviewsMode: ReviewHogReviewsTableRetrieveReviewMode | null
    reviewsPage: ReviewReviewsTablePageApi | null
    reviewsPageLoading: boolean
    reviewsPublished: boolean | null
    reviewsRepository: string | null
    reviewsRepositoryOptions: string[]
    reviewsScope: ReviewHogReviewsListScope
    reviewsStatus: ReviewHogReviewsTableRetrieveStatus | null
    savingSkillNames: string[]
    seenRepositories: string[]
    settings: ReviewUserSettingsApi | null
    settingsLoading: boolean
    triggerPrUrl: string
    triggerUrlHasFullReview: boolean
    triggerUrlResolving: boolean
    triggeringReview: boolean
    validators: ReviewValidatorConfigApi[] | null
    validatorsLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reviewHogSettingsLogicActions {
    applyDefaultReviewsScope: (scope: ReviewHogReviewsListScope) => {
        scope: ReviewHogReviewsListScope
    }
    backToAdoptSearch: () => {
        value: true
    }
    blockSingleActiveDeactivation: (kindLabel: string) => {
        kindLabel: string
    }
    chooseAdoptSource: (source: AdoptSource) => {
        source: AdoptSource
    }
    clearReviewsFilters: () => {
        value: true
    }
    closeAdoptSkillModal: () => {
        value: true
    }
    closePipelineDetail: () => {
        value: true
    }
    closeReviewDrawer: () => {
        value: true
    }
    followProjectDefault: (key: ProjectDefaultKey) => {
        key: ProjectDefaultKey
    }
    loadAdoptableSkills: (_?: any) => any
    loadAdoptableSkillsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAdoptableSkillsSuccess: (
        adoptableSkills: LLMSkillListApi[],
        payload?: any
    ) => {
        adoptableSkills: LLMSkillListApi[]
        payload?: any
    }
    loadAll: () => {
        value: true
    }
    loadBlindSpots: () => any
    loadBlindSpotsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadBlindSpotsSuccess: (
        blindSpots: ReviewBlindSpotsConfigApi[],
        payload?: any
    ) => {
        blindSpots: ReviewBlindSpotsConfigApi[]
        payload?: any
    }
    loadDeepSkillStats: () => any
    loadDeepSkillStatsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadDeepSkillStatsSuccess: (
        deepSkillStats: ReviewPerspectiveStatsApi,
        payload?: any
    ) => {
        deepSkillStats: ReviewPerspectiveStatsApi
        payload?: any
    }
    loadPerspectiveStats: (_?: any) => any
    loadPerspectiveStatsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPerspectiveStatsSuccess: (
        perspectiveStats: ReviewPerspectiveStatsApi,
        payload?: any
    ) => {
        perspectiveStats: ReviewPerspectiveStatsApi
        payload?: any
    }
    loadPerspectives: () => any
    loadPerspectivesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPerspectivesSuccess: (
        perspectives: ReviewPerspectiveConfigApi[],
        payload?: any
    ) => {
        perspectives: ReviewPerspectiveConfigApi[]
        payload?: any
    }
    loadResolutionSkills: () => any
    loadResolutionSkillsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadResolutionSkillsSuccess: (
        resolutionSkills: ReviewResolutionConfigApi[],
        payload?: any
    ) => {
        resolutionSkills: ReviewResolutionConfigApi[]
        payload?: any
    }
    loadReviewDetail: (reviewId: string) => string
    loadReviewDetailFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReviewDetailSuccess: (
        reviewDetail: ReviewDetailApi,
        payload?: string
    ) => {
        reviewDetail: ReviewDetailApi
        payload?: string
    }
    loadReviews: (_?: any) => any
    loadReviewsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReviewsSuccess: (
        reviewsPage: ReviewReviewsTablePageApi,
        payload?: any
    ) => {
        reviewsPage: ReviewReviewsTablePageApi
        payload?: any
    }
    loadSettings: () => any
    loadSettingsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSettingsSuccess: (
        settings: ReviewUserSettingsApi,
        payload?: any
    ) => {
        settings: ReviewUserSettingsApi
        payload?: any
    }
    loadValidators: () => any
    loadValidatorsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadValidatorsSuccess: (
        validators: ReviewValidatorConfigApi[],
        payload?: any
    ) => {
        validators: ReviewValidatorConfigApi[]
        payload?: any
    }
    markInitialLoadFailed: () => {
        value: true
    }
    openAdoptSkillModal: (kind: ReviewSkillKind) => {
        kind: ReviewSkillKind
    }
    openPipelineDetail: () => {
        value: true
    }
    openReviewDetail: (review: ReviewRecentReviewApi) => {
        review: ReviewRecentReviewApi
    }
    openReviewDetailById: (reviewId: string) => {
        reviewId: string
    }
    patchPerspectiveLocally: (
        skillName: string,
        enabled: boolean
    ) => {
        enabled: boolean
        skillName: string
    }
    selectBlindSpots: (skillName: string) => {
        skillName: string
    }
    selectResolutionSkill: (skillName: string) => {
        skillName: string
    }
    selectValidator: (skillName: string) => {
        skillName: string
    }
    setActiveTab: (tab: CodeReviewTab) => {
        tab: CodeReviewTab
    }
    setAdoptSlug: (slug: string) => {
        slug: string
    }
    setReviewDrawerTab: (tab: ReviewDrawerTab) => {
        tab: ReviewDrawerTab
    }
    setReviewsMode: (mode: ReviewHogReviewsTableRetrieveReviewMode | null) => {
        mode: ReviewHogReviewsTableRetrieveReviewMode | null
    }
    setReviewsPage: (page: number) => {
        page: number
    }
    setReviewsPublished: (published: boolean | null) => {
        published: boolean | null
    }
    setReviewsRepository: (repository: string | null) => {
        repository: string | null
    }
    setReviewsScope: (scope: ReviewHogReviewsListScope) => {
        scope: ReviewHogReviewsListScope
    }
    setReviewsStatus: (status: ReviewHogReviewsTableRetrieveStatus | null) => {
        status: ReviewHogReviewsTableRetrieveStatus | null
    }
    setSkillSaving: (
        skillName: string,
        saving: boolean
    ) => {
        saving: boolean
        skillName: string
    }
    setTriggerPrUrl: (prUrl: string) => {
        prUrl: string
    }
    startSkillAuthorTask: (kind: ReviewSkillKind) => {
        kind: ReviewSkillKind
    }
    startSkillAuthorTaskFinished: () => {
        value: true
    }
    startTriggeredReviewWatch: () => {
        value: true
    }
    stopTriggeredReviewWatch: () => {
        value: true
    }
    submitAdoptSkill: () => {
        value: true
    }
    submitAdoptSkillFinished: () => {
        value: true
    }
    submitAdoptSkillStarted: () => {
        value: true
    }
    submitTriggerReview: (runMode?: ReviewTriggerRequestRunModeEnumApi) => {
        runMode: ReviewTriggerRequestRunModeEnumApi
    }
    submitTriggerReviewFinished: () => {
        value: true
    }
    submitTriggerReviewStarted: () => {
        value: true
    }
    togglePerspective: (
        skillName: string,
        enabled: boolean
    ) => {
        enabled: boolean
        skillName: string
    }
    updateSettings: (patch: PatchedReviewUserSettingsApi) => PatchedReviewUserSettingsApi
    updateSettingsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    updateSettingsSuccess: (
        settings: ReviewUserSettingsApi,
        payload?: PatchedReviewUserSettingsApi
    ) => {
        settings: ReviewUserSettingsApi
        payload?: PatchedReviewUserSettingsApi
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reviewHogSettingsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        deepSkillKept: (
            deepSkillStats: ReviewPerspectiveStatsApi | null
        ) => Record<string, ReviewPerspectiveStatItemApi> | null
        deepValidationKept: (deepSkillStats: ReviewPerspectiveStatsApi | null) => {
            judged: number
            kept: number
        } | null
        adoptSkillGroups: (
            adoptableSkills: LLMSkillListApi[] | null,
            adoptSkillKind: ReviewSkillKind | null,
            perspectives: ReviewPerspectiveConfigApi[] | null,
            blindSpots: ReviewBlindSpotsConfigApi[] | null,
            validators: ReviewValidatorConfigApi[] | null,
            resolutionSkills: ReviewResolutionConfigApi[] | null
        ) => SkillPickerGroup[]
        adoptNewSkillName: (adoptSkillKind: ReviewSkillKind | null, adoptSlug: string) => string
        adoptSlugError: (
            adoptSlug: string,
            adoptSkillKind: ReviewSkillKind | null,
            adoptableSkills: LLMSkillListApi[] | null,
            perspectives: ReviewPerspectiveConfigApi[] | null,
            blindSpots: ReviewBlindSpotsConfigApi[] | null,
            validators: ReviewValidatorConfigApi[] | null,
            resolutionSkills: ReviewResolutionConfigApi[] | null
        ) => string | null
        reviews: (reviewsPage: ReviewReviewsTablePageApi | null) => ReviewRecentReviewApi[] | null
        reviewsFiltered: (
            reviewsRepository: string | null,
            reviewsMode: ReviewHogReviewsTableRetrieveReviewMode | null,
            reviewsStatus: ReviewHogReviewsTableRetrieveStatus | null,
            reviewsPublished: boolean | null
        ) => boolean
        reviewsRepositoryOptions: (seenRepositories: string[], reviewsRepository: string | null) => string[]
        reviewFindingsSplit: (
            reviewDetail: ReviewDetailApi | null,
            settings: ReviewUserSettingsApi | null
        ) => ReviewFindingsSplit | null
        triggerUrlHasFullReview: (triggerPrUrl: string, reviews: ReviewRecentReviewApi[] | null) => boolean
        triggerUrlResolving: (triggerPrUrl: string, reviews: ReviewRecentReviewApi[] | null) => boolean
        perspectiveScoreboard: (reviewDetail: ReviewDetailApi | null) => PerspectiveScore[] | null
    }
}

export type reviewHogSettingsLogicType = MakeLogicType<
    reviewHogSettingsLogicValues,
    reviewHogSettingsLogicActions,
    Record<string, any>,
    reviewHogSettingsLogicMeta
>

/**
 * State for the "Code review" scene: the user's ReviewHog settings (triggers + urgency
 * threshold) and the four skill lists (perspectives / blind-spot check / validation criteria /
 * resolution criteria) with their per-user enablement. Cardinality rules mirror the backend:
 * perspectives keep a min-1 floor; blind spots, validators, and resolution criteria are
 * exactly-one-active (deactivation is blocked, you switch by selecting another). "Create your
 * own …" kicks off an authoring agent task, mirroring the Inbox "Make a scout" flow.
 */
export const reviewHogSettingsLogic = kea<reviewHogSettingsLogicType>([
    path(['products', 'review_hog', 'frontend', 'reviewHogSettingsLogic']),

    actions({
        // Fires the four initial loads — also the retry entry point after a failed load.
        loadAll: true,
        togglePerspective: (skillName: string, enabled: boolean) => ({ skillName, enabled }),
        patchPerspectiveLocally: (skillName: string, enabled: boolean) => ({ skillName, enabled }),
        selectBlindSpots: (skillName: string) => ({ skillName }),
        selectValidator: (skillName: string) => ({ skillName }),
        selectResolutionSkill: (skillName: string) => ({ skillName }),
        // The active card's switch can't be turned off — exactly one stays active per kind.
        blockSingleActiveDeactivation: (kindLabel: string) => ({ kindLabel }),
        setSkillSaving: (skillName: string, saving: boolean) => ({ skillName, saving }),
        openReviewDetail: (review: ReviewRecentReviewApi) => ({ review }),
        // Opens the drawer for a review with no list row in hand — the `?review=` deep-link path
        // (PR status comments bake these links into GitHub). The drawer renders from the loaded
        // detail alone.
        openReviewDetailById: (reviewId: string) => ({ reviewId }),
        closeReviewDrawer: true,
        openPipelineDetail: true,
        closePipelineDetail: true,
        setActiveTab: (tab: CodeReviewTab) => ({ tab }),
        setReviewDrawerTab: (tab: ReviewDrawerTab) => ({ tab }),
        setReviewsScope: (scope: ReviewHogReviewsListScope) => ({ scope }),
        setReviewsPage: (page: number) => ({ page }),
        setReviewsRepository: (repository: string | null) => ({ repository }),
        setReviewsMode: (mode: ReviewHogReviewsTableRetrieveReviewMode | null) => ({ mode }),
        setReviewsStatus: (status: ReviewHogReviewsTableRetrieveStatus | null) => ({ status }),
        setReviewsPublished: (published: boolean | null) => ({ published }),
        clearReviewsFilters: true,
        // Auto-select a default scope (Everyone when the user has no reviews of their own)
        // without marking it as an explicit user choice, so a later real choice still wins.
        applyDefaultReviewsScope: (scope: ReviewHogReviewsListScope) => ({ scope }),
        startSkillAuthorTask: (kind: ReviewSkillKind) => ({ kind }),
        startSkillAuthorTaskFinished: true,
        // "Use an existing skill": pick a team skill, copy it under the kind's prefix, switch it on.
        openAdoptSkillModal: (kind: ReviewSkillKind) => ({ kind }),
        closeAdoptSkillModal: true,
        chooseAdoptSource: (source: AdoptSource) => ({ source }),
        backToAdoptSearch: true,
        setAdoptSlug: (slug: string) => ({ slug }),
        submitAdoptSkill: true,
        // Flipped by the listener (not the submit action itself) so a repeat dispatch mid-flight is
        // dropped before it POSTs, mirroring the trigger flow's guard.
        submitAdoptSkillStarted: true,
        submitAdoptSkillFinished: true,
        // Drops the user's own value, so the project default applies again. The API never stores a
        // value equal to the inherited one, so writing the project default clears the key.
        followProjectDefault: (key: ProjectDefaultKey) => ({ key }),
        setTriggerPrUrl: (prUrl: string) => ({ prUrl }),
        // Starts a run on the pasted PR URL: a review (which resolves comments per the user's
        // setting), a review without resolving, a resolve-only run, or a flash review — the split
        // button's variants.
        // The listener self-guards on `triggeringReview`, so a repeat dispatch mid-flight (Enter
        // spam, double click) is a no-op regardless of the source.
        submitTriggerReview: (
            runMode: ReviewTriggerRequestRunModeEnumApi = ReviewTriggerRequestRunModeEnumApi.Review
        ) => ({ runMode }),
        submitTriggerReviewStarted: true,
        submitTriggerReviewFinished: true,
        // Keeps the table polling until a just-triggered review's report row appears.
        startTriggeredReviewWatch: true,
        stopTriggeredReviewWatch: true,
        // Flags a load failure as the page-level one. Dispatched by the failure listeners only when
        // the failing surface has nothing loaded yet, so a background poll blip stays silent.
        markInitialLoadFailed: true,
    }),

    loaders(({ values }) => ({
        settings: [
            null as ReviewUserSettingsApi | null,
            {
                loadSettings: async () => await reviewHogSettingsRetrieve(currentProjectId()),
                updateSettings: async (patch: PatchedReviewUserSettingsApi, breakpoint) => {
                    const response = await reviewHogSettingsPartialUpdate(currentProjectId(), patch)
                    // A newer update is already in flight — drop this now-stale response.
                    breakpoint()
                    return response
                },
            },
        ],
        perspectives: [
            null as ReviewPerspectiveConfigApi[] | null,
            {
                loadPerspectives: async () => await reviewHogPerspectivesList(currentProjectId()),
            },
        ],
        blindSpots: [
            null as ReviewBlindSpotsConfigApi[] | null,
            {
                loadBlindSpots: async () => await reviewHogBlindSpotsList(currentProjectId()),
            },
        ],
        validators: [
            null as ReviewValidatorConfigApi[] | null,
            {
                loadValidators: async () => await reviewHogValidatorsList(currentProjectId()),
            },
        ],
        resolutionSkills: [
            null as ReviewResolutionConfigApi[] | null,
            {
                loadResolutionSkills: async () => await reviewHogResolutionList(currentProjectId()),
            },
        ],
        // Every live team skill, for the adopt picker. Fetched fresh on each modal open so a skill
        // created since the last open (e.g. by an authoring task) is offered. The picker's search,
        // grouping, and name-collision checks all assume the complete store, so the loader follows
        // the pagination to the end instead of trusting one page to cover it.
        adoptableSkills: [
            null as LLMSkillListApi[] | null,
            {
                loadAdoptableSkills: async (_ = null, breakpoint) => {
                    const skills: LLMSkillListApi[] = []
                    let hasMore = true
                    while (hasMore) {
                        // `offset: skills.length` adapts to the page size the server actually
                        // returned, so a server-side clamp below the requested limit skips nothing.
                        const response = await llmSkillsList(currentProjectId(), {
                            limit: ADOPTABLE_SKILLS_PAGE_SIZE,
                            offset: skills.length,
                        })
                        breakpoint()
                        skills.push(...response.results)
                        // An empty page stops the loop too, so a buggy `next` can never spin it forever.
                        hasMore = Boolean(response.next) && response.results.length > 0
                    }
                    return skills
                },
            },
        ],
        reviewsPage: [
            null as ReviewReviewsTablePageApi | null,
            {
                // The default param keeps the action zero-arg in the generated logic type.
                loadReviews: async (_ = null, breakpoint) => {
                    // urlToAction replays each deep-link filter in turn; debounce so only the settled set loads.
                    await breakpoint(1)
                    const response = await reviewHogReviewsTableRetrieve(currentProjectId(), {
                        scope: values.reviewsScope,
                        limit: REVIEWS_PAGE_SIZE,
                        offset: (values.reviewsCurrentPage - 1) * REVIEWS_PAGE_SIZE,
                        ...(values.reviewsRepository ? { repository: values.reviewsRepository } : {}),
                        ...(values.reviewsMode ? { review_mode: values.reviewsMode } : {}),
                        ...(values.reviewsStatus ? { status: values.reviewsStatus } : {}),
                        ...(values.reviewsPublished !== null ? { published: values.reviewsPublished } : {}),
                    })
                    // A filter or page change mid-flight dispatched a newer load — drop this stale response.
                    breakpoint()
                    return response
                },
            },
        ],
        reviewDetail: [
            null as ReviewDetailApi | null,
            {
                loadReviewDetail: async (reviewId: string, breakpoint) => {
                    const response = await reviewHogReviewsRetrieve(currentProjectId(), reviewId)
                    // A newer open (row click, ?review= navigation) dispatched a fresh load
                    // mid-flight — drop this stale response so out-of-order responses can't
                    // attach the wrong review's findings to the drawer.
                    breakpoint()
                    return response
                },
            },
        ],
        perspectiveStats: [
            null as ReviewPerspectiveStatsApi | null,
            {
                // The default param keeps the action zero-arg in the generated logic type.
                loadPerspectiveStats: async (_ = null, breakpoint) => {
                    const response = await reviewHogReviewsPerspectiveStatsRetrieve(currentProjectId(), {
                        scope: values.reviewsScope,
                    })
                    // A scope change mid-flight dispatched a newer load — drop this stale response.
                    breakpoint()
                    return response
                },
            },
        ],
        // The review skills on the Settings tab: the viewer's own last Deep reviews, whatever the
        // Activity tab's Mine / Everyone switch says, because only the person who starts a Deep
        // review picks its skills.
        deepSkillStats: [
            null as ReviewPerspectiveStatsApi | null,
            {
                loadDeepSkillStats: async () =>
                    await reviewHogReviewsPerspectiveStatsRetrieve(currentProjectId(), {
                        scope: ReviewHogReviewsPerspectiveStatsRetrieveScope.OwnDeep,
                    }),
            },
        ],
    })),

    reducers({
        settings: {
            // Optimistic: the switches/slider reflect the change immediately; a failure listener
            // reloads to reconcile.
            updateSettings: (state: ReviewUserSettingsApi | null, patch: PatchedReviewUserSettingsApi) =>
                state ? { ...state, ...patch } : state,
        },
        perspectives: {
            patchPerspectiveLocally: (state: ReviewPerspectiveConfigApi[] | null, { skillName, enabled }) =>
                state?.map((p) => (p.skill_name === skillName ? { ...p, enabled } : p)) ?? state,
        },
        blindSpots: {
            selectBlindSpots: (state: ReviewBlindSpotsConfigApi[] | null, { skillName }) =>
                state?.map((s) => ({ ...s, active: s.skill_name === skillName })) ?? state,
        },
        validators: {
            selectValidator: (state: ReviewValidatorConfigApi[] | null, { skillName }) =>
                state?.map((s) => ({ ...s, active: s.skill_name === skillName })) ?? state,
        },
        resolutionSkills: {
            selectResolutionSkill: (state: ReviewResolutionConfigApi[] | null, { skillName }) =>
                state?.map((s) => ({ ...s, active: s.skill_name === skillName })) ?? state,
        },
        savingSkillNames: [
            [] as string[],
            {
                setSkillSaving: (state, { skillName, saving }) =>
                    saving ? [...state, skillName] : state.filter((name) => name !== skillName),
            },
        ],
        // The clicked list row: the drawer header renders from it instantly while the detail loads.
        // Null on a deep-linked open (no row in hand) — the drawer then renders from the detail alone.
        openedReview: [
            null as ReviewRecentReviewApi | null,
            {
                openReviewDetail: (_, { review }) => review,
                openReviewDetailById: () => null,
            },
        ],
        // The review the drawer is showing (or loading), by id — set synchronously by both open
        // paths, so the URL sync can tell "this location event is my own write-back" apart from a
        // genuinely new deep link before the detail has loaded.
        openedReviewId: [
            null as string | null,
            {
                openReviewDetail: (_, { review }) => review.id,
                openReviewDetailById: (_, { reviewId }) => reviewId,
                closeReviewDrawer: () => null,
            },
        ],
        reviewDetail: {
            // Clear the previous review's detail so opening another row never flashes stale findings.
            openReviewDetail: () => null,
            openReviewDetailById: () => null,
        },
        reviewDrawerOpen: [
            false,
            {
                openReviewDetail: () => true,
                openReviewDetailById: () => true,
                closeReviewDrawer: () => false,
            },
        ],
        pipelineDetailOpen: [
            false,
            {
                openPipelineDetail: () => true,
                closePipelineDetail: () => false,
            },
        ],
        activeTab: [
            'activity' as CodeReviewTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        reviewDrawerTab: [
            'published' as ReviewDrawerTab,
            {
                setReviewDrawerTab: (_, { tab }) => tab,
                openReviewDetail: () => 'published' as ReviewDrawerTab,
                openReviewDetailById: () => 'published' as ReviewDrawerTab,
            },
        ],
        perspectiveStats: {
            // A different scope is different data — drop the old numbers so the stat cards show
            // skeletons instead of the wrong scope's stats while the reload is in flight.
            setReviewsScope: () => null,
            applyDefaultReviewsScope: () => null,
        },
        reviewsPage: {
            // Drop rows that no longer match the controls so the table shows loading. Poll refreshes keep them.
            setReviewsScope: () => null,
            applyDefaultReviewsScope: () => null,
            setReviewsPage: () => null,
            setReviewsRepository: () => null,
            setReviewsMode: () => null,
            setReviewsStatus: () => null,
            setReviewsPublished: () => null,
            clearReviewsFilters: () => null,
        },
        // A failed poll keeps its rows; the table shows the error only when it has none.
        reviewsFailed: [
            false,
            {
                loadReviews: () => false,
                loadReviewsSuccess: () => false,
                loadReviewsFailure: () => true,
            },
        ],
        // A page number rarely exists once the row set narrows, so every scope and filter change resets it.
        reviewsCurrentPage: [
            1,
            {
                setReviewsPage: (_, { page }) => page,
                setReviewsScope: () => 1,
                applyDefaultReviewsScope: () => 1,
                setReviewsRepository: () => 1,
                setReviewsMode: () => 1,
                setReviewsStatus: () => 1,
                setReviewsPublished: () => 1,
                clearReviewsFilters: () => 1,
            },
        ],
        reviewsRepository: [
            null as string | null,
            {
                setReviewsRepository: (_, { repository }) => repository,
                clearReviewsFilters: () => null,
            },
        ],
        reviewsMode: [
            null as ReviewHogReviewsTableRetrieveReviewMode | null,
            {
                setReviewsMode: (_, { mode }) => mode,
                clearReviewsFilters: () => null,
            },
        ],
        reviewsStatus: [
            null as ReviewHogReviewsTableRetrieveStatus | null,
            {
                setReviewsStatus: (_, { status }) => status,
                clearReviewsFilters: () => null,
            },
        ],
        reviewsPublished: [
            null as boolean | null,
            {
                setReviewsPublished: (_, { published }) => published,
                clearReviewsFilters: () => null,
            },
        ],
        // Kept across filter changes so picking one repository does not empty the other options.
        seenRepositories: [
            [] as string[],
            {
                loadReviewsSuccess: (state, { reviewsPage }) => {
                    const merged = Array.from(
                        new Set([...state, ...reviewsPage.results.map((review) => review.repository)])
                    ).sort()
                    return merged.length === state.length ? state : merged
                },
            },
        ],
        // The "Mine / Everyone" filter on the reviews table: it scopes the list AND every stat
        // surface fed by perspectiveStats (proof card, effectiveness cards on the Settings tab).
        // Skill lists and their toggles stay per-user regardless.
        reviewsScope: [
            ReviewHogReviewsListScope.Mine as ReviewHogReviewsListScope,
            { persist: true },
            {
                setReviewsScope: (_, { scope }) => scope,
                applyDefaultReviewsScope: (_, { scope }) => scope,
            },
        ],
        // Whether the user has explicitly picked a scope. Once true, the empty-list auto-default
        // no longer fires, so a deliberate choice of "Mine" is respected even with zero reviews.
        // A shared link is an explicit choice too, so URL hydration goes through setReviewsScope.
        hasUserChosenReviewsScope: [
            false,
            { persist: true },
            {
                setReviewsScope: () => true,
            },
        ],
        initialLoadFailed: [
            false,
            {
                loadAll: () => false,
                loadSettingsFailure: () => true,
                loadPerspectivesFailure: () => true,
                loadBlindSpotsFailure: () => true,
                loadValidatorsFailure: () => true,
                loadResolutionSkillsFailure: () => true,
                // perspectiveStats failures arrive via markInitialLoadFailed instead: its loader
                // also runs after a watched run finishes, where a one-off failure is not a
                // page-level one. Only a failure with nothing loaded yet (cards stuck on skeletons,
                // no retry path) is. The reviews table shows its own error state.
                markInitialLoadFailed: () => true,
            },
        ],
        creatingSkillKind: [
            // Guards the "Create your own …" buttons against double-submission while the task spins up.
            null as ReviewSkillKind | null,
            {
                startSkillAuthorTask: (_, { kind }) => kind,
                startSkillAuthorTaskFinished: () => null,
            },
        ],
        // Which kind the adopt modal is open for; null means closed.
        adoptSkillKind: [
            null as ReviewSkillKind | null,
            {
                openAdoptSkillModal: (_, { kind }) => kind,
                closeAdoptSkillModal: () => null,
            },
        ],
        // The picked source skill; non-null switches the modal from the picker to the confirm step.
        adoptSource: [
            null as AdoptSource | null,
            {
                chooseAdoptSource: (_, { source }) => source,
                backToAdoptSearch: () => null,
                openAdoptSkillModal: () => null,
                closeAdoptSkillModal: () => null,
            },
        ],
        adoptSlug: [
            '',
            {
                setAdoptSlug: (_, { slug }) => slug,
                openAdoptSkillModal: () => '',
                backToAdoptSearch: () => '',
            },
        ],
        adoptingSkill: [
            false,
            {
                submitAdoptSkillStarted: () => true,
                submitAdoptSkillFinished: () => false,
            },
        ],
        triggerPrUrl: [
            '',
            {
                setTriggerPrUrl: (_, { prUrl }) => prUrl,
            },
        ],
        triggeringReview: [
            false,
            {
                // Flipped by the listener (not the submit action itself) so the listener can tell a
                // first submit from an Enter-spam repeat and drop the repeat before it POSTs.
                submitTriggerReviewStarted: () => true,
                submitTriggerReviewFinished: () => false,
            },
        ],
        awaitingTriggeredReview: [
            false,
            {
                startTriggeredReviewWatch: () => true,
                stopTriggeredReviewWatch: () => false,
            },
        ],
    }),

    selectors({
        deepSkillKept: [
            (s) => [s.deepSkillStats],
            (deepSkillStats: ReviewPerspectiveStatsApi | null): Record<string, ReviewPerspectiveStatItemApi> | null =>
                deepSkillStats
                    ? Object.fromEntries(deepSkillStats.perspectives.map((item) => [item.skill_name, item]))
                    : null,
        ],
        // Verdicts carry no validator name, so the active validator gets the total over every skill.
        deepValidationKept: [
            (s) => [s.deepSkillStats],
            (deepSkillStats: ReviewPerspectiveStatsApi | null): { kept: number; judged: number } | null => {
                if (!deepSkillStats) {
                    return null
                }
                const kept = deepSkillStats.perspectives.reduce((sum, item) => sum + item.kept, 0)
                const dismissed = deepSkillStats.perspectives.reduce((sum, item) => sum + item.dismissed, 0)
                return { kept, judged: kept + dismissed }
            },
        ],
        // The adopt picker's two groups: teammates' ready-made skills of the kind (store rows with
        // the kind's prefix that aren't already cards above, i.e. not canonicals or own customs),
        // then every other team skill. Cross-kind review-hog skills land in the second group on
        // purpose: adopting, say, a validation bar as resolution criteria is legitimate reuse.
        adoptSkillGroups: [
            (s) => [
                s.adoptableSkills,
                s.adoptSkillKind,
                s.perspectives,
                s.blindSpots,
                s.validators,
                s.resolutionSkills,
            ],
            (
                adoptableSkills: LLMSkillListApi[] | null,
                adoptSkillKind: ReviewSkillKind | null,
                perspectives: ReviewPerspectiveConfigApi[] | null,
                blindSpots: ReviewBlindSpotsConfigApi[] | null,
                validators: ReviewValidatorConfigApi[] | null,
                resolutionSkills: ReviewResolutionConfigApi[] | null
            ): SkillPickerGroup[] => {
                if (!adoptSkillKind || !adoptableSkills) {
                    return []
                }
                const prefix = REVIEW_SKILL_PREFIX_BY_KIND[adoptSkillKind]
                const cardsByKind: Record<ReviewSkillKind, { skill_name: string }[] | null> = {
                    perspective: perspectives,
                    blind_spots: blindSpots,
                    validator: validators,
                    resolution: resolutionSkills,
                }
                const cardNames = new Set((cardsByKind[adoptSkillKind] ?? []).map((card) => card.skill_name))
                const toPickerSkill = (skill: LLMSkillListApi): { name: string; description: string } => ({
                    name: skill.name,
                    description: skill.description,
                })
                return [
                    {
                        key: 'teammates',
                        label: ADOPT_TEAMMATE_GROUP_LABELS[adoptSkillKind],
                        skills: adoptableSkills
                            .filter((skill) => skill.name.startsWith(prefix) && !cardNames.has(skill.name))
                            .map(toPickerSkill),
                    },
                    {
                        key: 'store',
                        label: 'All team skills',
                        skills: adoptableSkills.filter((skill) => !skill.name.startsWith(prefix)).map(toPickerSkill),
                    },
                ]
            },
        ],
        adoptNewSkillName: [
            (s) => [s.adoptSkillKind, s.adoptSlug],
            (adoptSkillKind: ReviewSkillKind | null, adoptSlug: string): string =>
                adoptSkillKind ? REVIEW_SKILL_PREFIX_BY_KIND[adoptSkillKind] + adoptSlug : '',
        ],
        adoptSlugError: [
            (s) => [
                s.adoptSlug,
                s.adoptSkillKind,
                s.adoptableSkills,
                s.perspectives,
                s.blindSpots,
                s.validators,
                s.resolutionSkills,
            ],
            (
                adoptSlug: string,
                adoptSkillKind: ReviewSkillKind | null,
                adoptableSkills: LLMSkillListApi[] | null,
                perspectives: ReviewPerspectiveConfigApi[] | null,
                blindSpots: ReviewBlindSpotsConfigApi[] | null,
                validators: ReviewValidatorConfigApi[] | null,
                resolutionSkills: ReviewResolutionConfigApi[] | null
            ): string | null => {
                if (!adoptSkillKind) {
                    return null
                }
                // Best-effort collision set: the store page plus the user's own cards. The server
                // still rejects anything this misses.
                const takenNames = new Set<string>([
                    ...(adoptableSkills?.map((skill) => skill.name) ?? []),
                    ...(perspectives?.map((card) => card.skill_name) ?? []),
                    ...(blindSpots?.map((card) => card.skill_name) ?? []),
                    ...(validators?.map((card) => card.skill_name) ?? []),
                    ...(resolutionSkills?.map((card) => card.skill_name) ?? []),
                ])
                return validateAdoptSlug(adoptSlug, adoptSkillKind, takenNames)
            },
        ],
        reviews: [
            (s) => [s.reviewsPage],
            (reviewsPage: ReviewReviewsTablePageApi | null): ReviewRecentReviewApi[] | null =>
                reviewsPage?.results ?? null,
        ],
        reviewsFiltered: [
            (s) => [s.reviewsRepository, s.reviewsMode, s.reviewsStatus, s.reviewsPublished],
            (
                repository: string | null,
                mode: ReviewHogReviewsTableRetrieveReviewMode | null,
                status: ReviewHogReviewsTableRetrieveStatus | null,
                published: boolean | null
            ): boolean => repository !== null || mode !== null || status !== null || published !== null,
        ],
        // The selected repository stays an option even before a page with it has loaded (a deep link).
        reviewsRepositoryOptions: [
            (s) => [s.seenRepositories, s.reviewsRepository],
            (seenRepositories: string[], reviewsRepository: string | null): string[] =>
                reviewsRepository && !seenRepositories.includes(reviewsRepository)
                    ? [...seenRepositories, reviewsRepository].sort()
                    : seenRepositories,
        ],
        // Splits the detail's valid findings by the threshold the run actually gated on
        // (`run_urgency_threshold`, stamped at finalize). Only rows that predate the stamp fall
        // back to the viewer's current setting — an approximation that can misbucket when the
        // run's acting user or their settings differ from the viewer's.
        reviewFindingsSplit: [
            (s) => [s.reviewDetail, s.settings],
            (
                reviewDetail: ReviewDetailApi | null,
                settings: ReviewUserSettingsApi | null
            ): ReviewFindingsSplit | null => {
                if (!reviewDetail) {
                    return null
                }
                const threshold = reviewDetail.run_urgency_threshold ?? settings?.urgency_threshold ?? 'consider'
                const thresholdRank = REVIEW_PRIORITY_RANK[threshold]
                return {
                    published: reviewDetail.findings.filter(
                        (f) => REVIEW_PRIORITY_RANK[f.effective_priority] >= thresholdRank
                    ),
                    belowThreshold: reviewDetail.findings.filter(
                        (f) => REVIEW_PRIORITY_RANK[f.effective_priority] < thresholdRank
                    ),
                }
            },
        ],
        // Flash does not run on a pull request after a Full review was published there. Only PRs the
        // list shows are known here; the trigger endpoint refuses the others with the same reason.
        triggerUrlHasFullReview: [
            (s) => [s.triggerPrUrl, s.reviews],
            (triggerPrUrl: string, reviews: ReviewRecentReviewApi[] | null): boolean => {
                const target = parsePrPath(triggerPrUrl)
                return (
                    !!target &&
                    (reviews ?? []).some(
                        (review) => review.full_review_published && parsePrPath(review.github_url) === target
                    )
                )
            },
        ],
        // Mirrors the server-side busy-guard for PRs the list already shows, so the trigger button
        // explains the refusal up front instead of surfacing it as a submit error.
        triggerUrlResolving: [
            (s) => [s.triggerPrUrl, s.reviews],
            (triggerPrUrl: string, reviews: ReviewRecentReviewApi[] | null): boolean => {
                const target = parsePrPath(triggerPrUrl)
                return (
                    !!target &&
                    (reviews ?? []).some(
                        (review) =>
                            review.resolution?.resolution_status === 'resolving' &&
                            parsePrPath(review.github_url) === target
                    )
                )
            },
        ],
        perspectiveScoreboard: [
            (s) => [s.reviewDetail],
            (reviewDetail: ReviewDetailApi | null): PerspectiveScore[] | null => {
                if (!reviewDetail?.findings.length) {
                    return null
                }
                const counts = new Map<string, number>()
                for (const finding of reviewDetail.findings) {
                    const skillName = finding.source_perspective ?? 'unknown'
                    counts.set(skillName, (counts.get(skillName) ?? 0) + 1)
                }
                return Array.from(counts, ([skillName, count]) => ({ skillName, count })).sort(
                    (a, b) => b.count - a.count
                )
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        // Every response decides again whether to poll; re-adding under the same key replaces the timer.
        loadReviewsSuccess: () => {
            const anyInProgress = values.reviews?.some((review) => review.in_progress) ?? false
            // The watch runs its full window: an unrelated running review would satisfy an early-stop check
            // and could finish before the triggered row appears.
            if (anyInProgress || values.awaitingTriggeredReview) {
                cache.disposables.add(() => {
                    const pollTimer = window.setInterval(() => actions.loadReviews(), IN_PROGRESS_POLL_INTERVAL_MS)
                    return () => clearInterval(pollTimer)
                }, 'reviewsPoll')
            } else {
                cache.disposables.dispose('reviewsPoll')
            }
            // A run finishing moves numbers beyond the list: the stats cards aggregate completed
            // turns, and an open drawer still shows the report's previous turn. A poll response is
            // the only place a completion becomes visible, so fan the refresh out from here.
            const previousRuns: Map<string, ReviewRunMarker> | undefined = cache.lastSeenRuns
            const currentRuns = new Map<string, ReviewRunMarker>()
            for (const review of values.reviews ?? []) {
                currentRuns.set(review.id, { inProgress: review.in_progress, runCount: review.run_count })
            }
            cache.lastSeenRuns = currentRuns
            if (previousRuns) {
                const finishedIds = Array.from(currentRuns.entries())
                    .filter(([id, run]) => {
                        const before = previousRuns.get(id)
                        return !!before && ((before.inProgress && !run.inProgress) || run.runCount > before.runCount)
                    })
                    .map(([id]) => id)
                // Under the Running filter a finished review leaves the page, so count it as finished too.
                for (const [id, before] of previousRuns) {
                    if (before.inProgress && !currentRuns.has(id)) {
                        finishedIds.push(id)
                    }
                }
                if (finishedIds.length) {
                    actions.loadPerspectiveStats()
                    actions.loadDeepSkillStats()
                    if (
                        values.reviewDrawerOpen &&
                        values.openedReviewId &&
                        finishedIds.includes(values.openedReviewId)
                    ) {
                        actions.loadReviewDetail(values.openedReviewId)
                    }
                }
            }
            // No own reviews: default to the whole project, unless the user chose a scope or a filter is set.
            if (
                values.reviewsPage?.count === 0 &&
                values.reviewsScope === ReviewHogReviewsListScope.Mine &&
                !values.hasUserChosenReviewsScope &&
                !values.reviewsFiltered
            ) {
                actions.applyDefaultReviewsScope(ReviewHogReviewsListScope.Everyone)
            }
        },
        startTriggeredReviewWatch: () => {
            // Bounded: a run that dies before creating its report row must not poll forever. The
            // next table load after expiry sees no in-progress rows and disposes the poll itself.
            cache.disposables.add(() => {
                const expiryTimer = window.setTimeout(
                    () => actions.stopTriggeredReviewWatch(),
                    TRIGGERED_REVIEW_WATCH_TIMEOUT_MS
                )
                return () => clearTimeout(expiryTimer)
            }, 'triggeredReviewWatch')
        },
        stopTriggeredReviewWatch: () => {
            cache.disposables.dispose('triggeredReviewWatch')
        },
        setReviewsScope: () => {
            // A different scope is a different list; start the finished-run comparison fresh.
            cache.lastSeenRuns = undefined
            actions.loadReviews()
            actions.loadPerspectiveStats()
        },
        applyDefaultReviewsScope: () => {
            cache.lastSeenRuns = undefined
            actions.loadReviews()
            actions.loadPerspectiveStats()
        },
        setReviewsPage: () => actions.loadReviews(),
        setReviewsRepository: () => actions.loadReviews(),
        setReviewsMode: () => actions.loadReviews(),
        setReviewsStatus: () => actions.loadReviews(),
        setReviewsPublished: () => actions.loadReviews(),
        clearReviewsFilters: () => actions.loadReviews(),
        loadAll: () => {
            actions.loadSettings()
            actions.loadPerspectives()
            actions.loadBlindSpots()
            actions.loadValidators()
            actions.loadResolutionSkills()
            actions.loadReviews()
            actions.loadPerspectiveStats()
            actions.loadDeepSkillStats()
        },
        followProjectDefault: ({ key }) => {
            const projectDefaults = values.settings?.project_defaults
            if (!projectDefaults) {
                return
            }
            actions.updateSettings({ [key]: projectDefaults[key] })
        },
        updateSettingsFailure: () => {
            // The global loaders toast already surfaced the error; just reconcile the optimistic state.
            actions.loadSettings()
        },
        loadPerspectiveStatsFailure: () => {
            if (values.perspectiveStats === null) {
                actions.markInitialLoadFailed()
            }
        },
        togglePerspective: async ({ skillName, enabled }) => {
            // Min-1 floor, mirrored from the backend so the block is instant (the server still 400s).
            const enabledCount = values.perspectives?.filter((p) => p.enabled).length ?? 0
            if (!enabled && enabledCount <= 1) {
                lemonToast.info('Keep at least one perspective enabled')
                return
            }
            actions.patchPerspectiveLocally(skillName, enabled)
            actions.setSkillSaving(skillName, true)
            try {
                await reviewHogPerspectivesPartialUpdate(currentProjectId(), skillName, { enabled })
            } catch (error: any) {
                // `data?.[0]`: DRF renders bare-string ValidationErrors (e.g. the min-1 floor) as a list.
                lemonToast.error(
                    error?.detail || error?.data?.[0] || error?.message || 'Failed to update the perspective'
                )
                actions.loadPerspectives()
            } finally {
                actions.setSkillSaving(skillName, false)
            }
        },
        selectBlindSpots: async ({ skillName }) => {
            actions.setSkillSaving(skillName, true)
            try {
                await reviewHogBlindSpotsPartialUpdate(currentProjectId(), skillName, { active: true })
            } catch (error: any) {
                lemonToast.error(
                    error?.detail || error?.data?.[0] || error?.message || 'Failed to select the blind-spot check'
                )
                actions.loadBlindSpots()
            } finally {
                actions.setSkillSaving(skillName, false)
            }
        },
        selectValidator: async ({ skillName }) => {
            actions.setSkillSaving(skillName, true)
            try {
                await reviewHogValidatorsPartialUpdate(currentProjectId(), skillName, { active: true })
            } catch (error: any) {
                lemonToast.error(
                    error?.detail || error?.data?.[0] || error?.message || 'Failed to select the validation criteria'
                )
                actions.loadValidators()
            } finally {
                actions.setSkillSaving(skillName, false)
            }
        },
        selectResolutionSkill: async ({ skillName }) => {
            actions.setSkillSaving(skillName, true)
            try {
                await reviewHogResolutionPartialUpdate(currentProjectId(), skillName, { active: true })
            } catch (error: any) {
                lemonToast.error(
                    error?.detail || error?.data?.[0] || error?.message || 'Failed to select the resolution criteria'
                )
                actions.loadResolutionSkills()
            } finally {
                actions.setSkillSaving(skillName, false)
            }
        },
        blockSingleActiveDeactivation: ({ kindLabel }) => {
            lemonToast.info(`One ${kindLabel} always runs — switch by selecting another one`)
        },
        openAdoptSkillModal: () => {
            actions.loadAdoptableSkills()
        },
        loadAdoptableSkillsFailure: () => {
            // Without this the picker would render its "no skills yet" empty state over a fetch
            // error. Closing keeps the states honest; reopening retries the load.
            lemonToast.error("Couldn't load your team's skills. Open the picker again to retry.")
            actions.closeAdoptSkillModal()
        },
        chooseAdoptSource: ({ source }) => {
            if (values.adoptSkillKind) {
                actions.setAdoptSlug(defaultAdoptSlug(source.name, values.adoptSkillKind))
            }
        },
        submitAdoptSkill: async () => {
            const kind = values.adoptSkillKind
            const source = values.adoptSource
            if (!kind || !source || values.adoptingSkill || values.adoptSlugError) {
                return
            }
            const newName = values.adoptNewSkillName
            actions.submitAdoptSkillStarted()
            try {
                await llmSkillsNameDuplicateCreate(currentProjectId(), source.name, { new_name: newName })
            } catch (error: any) {
                // Kept open so a name conflict can be fixed in place; the server's detail names it.
                lemonToast.error(error?.data?.detail || error?.detail || error?.message || "Couldn't copy the skill")
                actions.submitAdoptSkillFinished()
                return
            }
            try {
                if (kind === 'perspective') {
                    await reviewHogPerspectivesPartialUpdate(currentProjectId(), newName, { enabled: true })
                } else if (kind === 'blind_spots') {
                    await reviewHogBlindSpotsPartialUpdate(currentProjectId(), newName, { active: true })
                } else if (kind === 'validator') {
                    await reviewHogValidatorsPartialUpdate(currentProjectId(), newName, { active: true })
                } else {
                    await reviewHogResolutionPartialUpdate(currentProjectId(), newName, { active: true })
                }
                lemonToast.success('Skill copied. It now runs on your PR reviews.')
            } catch {
                // The copy exists even though switching it on failed: close to its new card and let
                // the user flip it on there.
                lemonToast.error("Copied the skill, but couldn't switch it on. Turn it on from its card.")
            }
            if (kind === 'perspective') {
                actions.loadPerspectives()
            } else if (kind === 'blind_spots') {
                actions.loadBlindSpots()
            } else if (kind === 'validator') {
                actions.loadValidators()
            } else {
                actions.loadResolutionSkills()
            }
            actions.submitAdoptSkillFinished()
            actions.closeAdoptSkillModal()
        },
        openReviewDetail: ({ review }) => {
            actions.loadReviewDetail(review.id)
        },
        openReviewDetailById: ({ reviewId }) => {
            actions.loadReviewDetail(reviewId)
        },
        loadReviewDetailFailure: () => {
            // Only the deep-link path has no list row keeping the drawer meaningful — a failed
            // load there (stale link, deleted report) would strand an open drawer of skeletons.
            if (values.reviewDrawerOpen && !values.openedReview) {
                lemonToast.error("That review couldn't be opened. The link may be stale, or the review deleted.")
                actions.closeReviewDrawer()
            }
        },
        submitTriggerReview: async ({ runMode }) => {
            if (values.triggeringReview) {
                // A request is already in flight — the disabled button can't stop an Enter keypress
                // in the input, so the guard lives here, covering every dispatch source.
                return
            }
            const prUrl = values.triggerPrUrl.trim()
            if (!prUrl) {
                return
            }
            actions.submitTriggerReviewStarted()
            try {
                const response = await reviewHogReviewsTriggerCreate(currentProjectId(), {
                    pr_url: prUrl,
                    run_mode: runMode,
                })
                actions.setTriggerPrUrl('')
                if (response.status === 'already_reviewed') {
                    // No run started — the PR's current commit already has a published review.
                    lemonToast.info(
                        'This pull request was already reviewed at its current commit. Find it under Reviews.'
                    )
                } else if (response.status === 'joined_running_review') {
                    lemonToast.info('Your request joined the review queue. Find it under Reviews.')
                } else if (runMode === ReviewTriggerRequestRunModeEnumApi.ResolveOnly) {
                    // Resolve-only runs don't create the report activity the review watch polls for,
                    // so a toast is the feedback: progress shows up on the pull request itself.
                    lemonToast.success(
                        'Resolving comments on the pull request. Replies and fixes will land there as threads settle.'
                    )
                } else {
                    lemonToast.success('Review started. It will appear under Reviews as it runs.')
                    // The review's report row is created seconds later by the workflow's fetch step,
                    // so one immediate reload usually misses it — arm the watch before reloading.
                    actions.startTriggeredReviewWatch()
                }
                actions.loadReviews()
            } catch (error: any) {
                // The trigger endpoint's rejections come back as `{error: "..."}` bodies.
                lemonToast.error(error?.data?.error || error?.detail || error?.message || 'Failed to start the review')
            } finally {
                actions.submitTriggerReviewFinished()
            }
        },
        startSkillAuthorTask: async ({ kind }) => {
            // Task-kickoff mirroring the Inbox "Make a scout" flow: create an agent task from a
            // templated authoring prompt, then navigate to it. Not a live chat.
            const { title, prompt } = SKILL_AUTHOR_TASKS[kind]
            try {
                let repository: string | undefined
                try {
                    const { repositories } = await api.tasks.repositories()
                    repository = repositories[0]
                } catch {
                    repository = undefined
                }
                const task = await api.tasks.create({
                    title,
                    description: prompt,
                    origin_product: OriginProduct.USER_CREATED,
                    repository,
                })
                router.actions.push(urls.taskDetail(task.id))
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || `Failed to start "${title}"`)
            } finally {
                actions.startSkillAuthorTaskFinished()
            }
        },
    })),

    // An explicit scope pick is mirrored to the URL (`?reviews_scope=everyone`) so a specific view
    // can be shared via a link; the default scope keeps the URL clean. The auto-default deliberately
    // does NOT write the URL: hydrating from a link marks the scope as chosen (below), so mirroring
    // the fallback would silently upgrade it into a permanent explicit choice on reload.
    // The tab mirrors to `?tab=settings` so a link can open the Settings tab; Activity keeps the URL clean.
    // The table's filters and page mirror to `reviews_*` params the same way, so a filtered view
    // can be shared too; each default keeps its param out of the URL.
    // The drawer mirrors to `?review=<report id>` the same way — a PERMANENT PUBLIC CONTRACT (PR
    // status comments bake these links into GitHub, where they are never re-edited). Always
    // `replace`, never push, so opening/closing the drawer doesn't stack history entries.
    actionToUrl(({ values }) => {
        const withReviewParam = (
            review: string | undefined
        ): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => [
            router.values.location.pathname,
            { ...router.values.searchParams, review },
            router.values.hashParams,
            { replace: true },
        ]
        const withTableParams = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => [
            router.values.location.pathname,
            {
                ...router.values.searchParams,
                reviews_scope: values.reviewsScope === ReviewHogReviewsListScope.Mine ? undefined : values.reviewsScope,
                reviews_repository: values.reviewsRepository ?? undefined,
                reviews_mode: values.reviewsMode ?? undefined,
                reviews_status: values.reviewsStatus ?? undefined,
                reviews_published: values.reviewsPublished === null ? undefined : String(values.reviewsPublished),
                reviews_page: values.reviewsCurrentPage > 1 ? String(values.reviewsCurrentPage) : undefined,
            },
            router.values.hashParams,
            { replace: true },
        ]
        return {
            setReviewsScope: withTableParams,
            setReviewsPage: withTableParams,
            setReviewsRepository: withTableParams,
            setReviewsMode: withTableParams,
            setReviewsStatus: withTableParams,
            setReviewsPublished: withTableParams,
            clearReviewsFilters: withTableParams,
            setActiveTab: (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    tab: values.activeTab === 'activity' ? undefined : values.activeTab,
                },
                router.values.hashParams,
                { replace: true },
            ],
            openReviewDetail: ({ review }) => withReviewParam(review.id),
            openReviewDetailById: ({ reviewId }) => withReviewParam(reviewId),
            closeReviewDrawer: () => withReviewParam(undefined),
        }
    }),

    urlToAction(({ actions, values }) => ({
        [urls.codeReview()]: (_, searchParams) => {
            const parsed = searchParams.reviews_scope
            if (
                (parsed === ReviewHogReviewsListScope.Mine || parsed === ReviewHogReviewsListScope.Everyone) &&
                parsed !== values.reviewsScope
            ) {
                actions.setReviewsScope(parsed)
            }
            // Guard each against its current value: every filter setter resets the page, so
            // replaying an unchanged filter on a deep link would knock the reader back to page 1.
            // The page goes last for the same reason.
            const repository =
                typeof searchParams.reviews_repository === 'string' ? searchParams.reviews_repository : null
            if (repository !== values.reviewsRepository) {
                actions.setReviewsRepository(repository)
            }
            const mode = Object.values(ReviewHogReviewsTableRetrieveReviewMode).find(
                (value) => value === searchParams.reviews_mode
            )
            if ((mode ?? null) !== values.reviewsMode) {
                actions.setReviewsMode(mode ?? null)
            }
            const status = Object.values(ReviewHogReviewsTableRetrieveStatus).find(
                (value) => value === searchParams.reviews_status
            )
            if ((status ?? null) !== values.reviewsStatus) {
                actions.setReviewsStatus(status ?? null)
            }
            // kea-router parses `true` / `false` into booleans; the string forms cover a hand-edited link.
            const publishedParam = String(searchParams.reviews_published)
            const published = publishedParam === 'true' ? true : publishedParam === 'false' ? false : null
            if (published !== values.reviewsPublished) {
                actions.setReviewsPublished(published)
            }
            // A hand-edited link can carry 0, -1 or Infinity, which would send an offset the API rejects.
            const pageParam = Number(searchParams.reviews_page ?? 1)
            const page = Number.isSafeInteger(pageParam) && pageParam > 0 ? pageParam : 1
            if (page !== values.reviewsCurrentPage) {
                actions.setReviewsPage(page)
            }
            const tab: CodeReviewTab = searchParams.tab === 'settings' ? 'settings' : 'activity'
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
            // ?review=<report id>: open that review's drawer. `openedReviewId` (set synchronously by
            // both open paths) makes the guard hold before the detail loads, so the open's own URL
            // write-back — a repeat location event with the same param — can't re-dispatch forever.
            const reviewParam = searchParams.review
            if (typeof reviewParam === 'string' && reviewParam && reviewParam !== values.openedReviewId) {
                actions.openReviewDetailById(reviewParam)
            } else if (!reviewParam && values.reviewDrawerOpen) {
                // Navigation that drops the param (back/forward, a pasted URL without it) closes
                // the drawer — otherwise the URL and the visible report disagree.
                actions.closeReviewDrawer()
            }
        },
    })),

    afterMount(({ actions, cache }) => {
        actions.loadAll()
        // One immediate list check on tab return. The poll's own interval is paused while hidden
        // and resumes with a full interval still to wait, which reads as stale exactly when the
        // user looks. Registered non-pausing: a paused listener is re-attached during the same
        // visibilitychange dispatch it needs to observe, and listeners added mid-dispatch don't
        // run for that event.
        cache.disposables.add(
            () => {
                const onVisibilityChange = (): void => {
                    if (!document.hidden) {
                        actions.loadReviews()
                    }
                }
                document.addEventListener('visibilitychange', onVisibilityChange)
                return () => document.removeEventListener('visibilitychange', onVisibilityChange)
            },
            'visibilityRefresh',
            { pauseOnPageHidden: false }
        )
    }),
])
