import { MakeLogicType, actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/posthog_ai/frontend/types/taskTypes'
import {
    reviewHogBlindSpotsList,
    reviewHogBlindSpotsPartialUpdate,
    reviewHogPerspectivesList,
    reviewHogPerspectivesPartialUpdate,
    reviewHogReviewsList,
    reviewHogReviewsPerspectiveStatsRetrieve,
    reviewHogReviewsRetrieve,
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
    ReviewPerspectiveStatsApi,
    ReviewRecentReviewApi,
    ReviewRecentReviewsPageApi,
    ReviewUserSettingsApi,
    ReviewValidatorConfigApi,
} from 'products/review_hog/frontend/generated/api.schemas'
import { ReviewHogReviewsListScope } from 'products/review_hog/frontend/generated/api.schemas'

export type ReviewSkillKind = 'perspective' | 'blind_spots' | 'validator'

export type ReviewDrawerTab = 'published' | 'below_threshold' | 'dismissed' | 'chunks' | 'review'

export const REVIEW_PRIORITY_RANK: Record<ReviewIssuePriorityEnumApi, number> = {
    consider: 0,
    should_fix: 1,
    must_fix: 2,
}

// While a review is running, the list refreshes on this cadence so the stage/progress row is live.
const IN_PROGRESS_POLL_INTERVAL_MS = 10_000

/** The review list's initial depth, the step each "Show more" adds, and what "Show fewer" collapses to. */
export const REVIEWS_PAGE_SIZE = 5

/** Mirrors MAX_REVIEWS_LIMIT in reviews.py — the API 400s above this, so growth must stop here. */
export const MAX_REVIEWS_LIMIT = 100

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

/** The skill a "View skill" click opens in the read-only drawer. */
export interface ViewedSkill {
    title: string
    body: string
    /** The `review-hog-*` skill name, for the drawer's link to the skill's editor page. */
    skillName: string
}

// Thin scout-style kickoff pointers (mirrors SCOUT_AUTHOR_PROMPT): the actual authoring guide —
// pipeline context, naming contract, per-kind body shape, activation steps — lives in the
// `review-hog-authoring` team skill (canonical source: products/review_hog/skills/), synced per
// team like the perspectives. Keep knowledge there, not here.
const SKILL_AUTHOR_TASKS: Record<ReviewSkillKind, { title: string; prompt: string }> = {
    perspective: {
        title: 'Create a ReviewHog perspective',
        prompt: `I'd like to create a custom ReviewHog review perspective for this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it — follow its review-perspective path.

Ground yourself per that skill first, then ask me what my perspective should focus on and offer a few concrete directions the current set doesn't already cover. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: list the team's review-hog-perspective-* skills and read a canonical one to learn the shape before authoring.`,
    },
    blind_spots: {
        title: 'Create a ReviewHog blind-spot check',
        prompt: `I'd like to create a custom ReviewHog blind-spot check for this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it — follow its blind-spot-check path.

Ground yourself per that skill first, then ask me what my sweep should emphasize and offer a few concrete directions. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: read the canonical review-hog-blind-spots-general skill to learn the shape before authoring.`,
    },
    validator: {
        title: 'Create ReviewHog validation criteria',
        prompt: `I'd like to create custom ReviewHog validation criteria for this PostHog project.

Use the review-hog-authoring skill from the PostHog MCP to guide creating it — follow its validation-criteria path.

Ground yourself per that skill first, then ask me how my bar should differ — stricter, more lenient, or weighted toward specific concerns — and offer a few concrete directions. Once I pick, author the skill end to end and tell me how to switch it on.

If the review-hog-authoring skill is unavailable, fall back to the PostHog MCP skill tools directly: read the canonical review-hog-validation-criteria skill to learn the shape before authoring.`,
    },
}

function currentProjectId(): string {
    return String(teamLogic.values.currentTeamId)
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reviewHogSettingsLogicValues {
    blindSpots: ReviewBlindSpotsConfigApi[] | null
    blindSpotsLoading: boolean
    creatingSkillKind: ReviewSkillKind | null
    expandedReviewIds: string[]
    hasUserChosenReviewsScope: boolean
    initialLoadFailed: boolean
    openedReview: ReviewRecentReviewApi | null
    perspectiveScoreboard: PerspectiveScore[] | null
    perspectiveStats: ReviewPerspectiveStatsApi | null
    perspectiveStatsLoading: boolean
    perspectives: ReviewPerspectiveConfigApi[] | null
    perspectivesLoading: boolean
    recentReviews: ReviewRecentReviewApi[] | null
    recentReviewsLoading: boolean
    reviewDetail: ReviewDetailApi | null
    reviewDetailLoading: boolean
    reviewDrawerOpen: boolean
    reviewDrawerTab: ReviewDrawerTab
    reviewFindingsSplit: ReviewFindingsSplit | null
    reviewsScope: ReviewHogReviewsListScope
    savingSkillNames: string[]
    settings: ReviewUserSettingsApi | null
    settingsLoading: boolean
    skillDrawerOpen: boolean
    validators: ReviewValidatorConfigApi[] | null
    validatorsLoading: boolean
    viewedSkill: ViewedSkill | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reviewHogSettingsLogicActions {
    applyDefaultReviewsScope: (scope: ReviewHogReviewsListScope) => {
        scope: ReviewHogReviewsListScope
    }
    blockSingleActiveDeactivation: (kindLabel: string) => {
        kindLabel: string
    }
    closeReviewDrawer: () => {
        value: true
    }
    closeSkillDrawer: () => {
        value: true
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
    loadPerspectiveStats: () => any
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
    loadRecentReviews: (_?: any) => any
    loadRecentReviewsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRecentReviewsSuccess: (
        recentReviews: ReviewRecentReviewApi[],
        payload?: any
    ) => {
        recentReviews: ReviewRecentReviewApi[]
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
    openReviewDetail: (review: ReviewRecentReviewApi) => {
        review: ReviewRecentReviewApi
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
    selectValidator: (skillName: string) => {
        skillName: string
    }
    setReviewDrawerTab: (tab: ReviewDrawerTab) => {
        tab: ReviewDrawerTab
    }
    setReviewsScope: (scope: ReviewHogReviewsListScope) => {
        scope: ReviewHogReviewsListScope
    }
    setSkillSaving: (
        skillName: string,
        saving: boolean
    ) => {
        saving: boolean
        skillName: string
    }
    startSkillAuthorTask: (kind: ReviewSkillKind) => {
        kind: ReviewSkillKind
    }
    startSkillAuthorTaskFinished: () => {
        value: true
    }
    togglePerspective: (
        skillName: string,
        enabled: boolean
    ) => {
        enabled: boolean
        skillName: string
    }
    toggleReviewRowExpanded: (reviewId: string) => {
        reviewId: string
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
    viewSkill: (skill: ViewedSkill) => {
        skill: ViewedSkill
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reviewHogSettingsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        reviewFindingsSplit: (
            reviewDetail: ReviewDetailApi | null,
            settings: ReviewUserSettingsApi | null
        ) => ReviewFindingsSplit | null
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
 * threshold) and the three skill lists (perspectives / blind-spot check / validation criteria)
 * with their per-user enablement. Cardinality rules mirror the backend: perspectives keep a
 * min-1 floor, blind spots and validators are exactly-one-active (deactivation is blocked,
 * you switch by selecting another). "Create your own …" kicks off an authoring agent task,
 * mirroring the Inbox "Make a scout" flow.
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
        // The active card's switch can't be turned off — exactly one stays active per kind.
        blockSingleActiveDeactivation: (kindLabel: string) => ({ kindLabel }),
        setSkillSaving: (skillName: string, saving: boolean) => ({ skillName, saving }),
        viewSkill: (skill: ViewedSkill) => ({ skill }),
        closeSkillDrawer: true,
        openReviewDetail: (review: ReviewRecentReviewApi) => ({ review }),
        closeReviewDrawer: true,
        setReviewDrawerTab: (tab: ReviewDrawerTab) => ({ tab }),
        toggleReviewRowExpanded: (reviewId: string) => ({ reviewId }),
        setReviewsScope: (scope: ReviewHogReviewsListScope) => ({ scope }),
        showMoreReviews: true,
        showFewerReviews: true,
        // Auto-select a default scope (Entire project when the user has no reviews of their own)
        // without marking it as an explicit user choice, so a later real choice still wins.
        applyDefaultReviewsScope: (scope: ReviewHogReviewsListScope) => ({ scope }),
        startSkillAuthorTask: (kind: ReviewSkillKind) => ({ kind }),
        startSkillAuthorTaskFinished: true,
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
        recentReviewsPage: [
            null as ReviewRecentReviewsPageApi | null,
            {
                // The default param keeps the action zero-arg in the generated logic type.
                loadRecentReviews: async (_ = null, breakpoint) => {
                    const { reviewsScope: scope, reviewsLimit: limit } = values
                    const response = await reviewHogReviewsList(currentProjectId(), { scope, limit })
                    // A scope or limit change mid-flight dispatched a newer load — drop this stale response.
                    breakpoint()
                    return response
                },
            },
        ],
        reviewDetail: [
            null as ReviewDetailApi | null,
            {
                loadReviewDetail: async (reviewId: string) =>
                    await reviewHogReviewsRetrieve(currentProjectId(), reviewId),
            },
        ],
        perspectiveStats: [
            null as ReviewPerspectiveStatsApi | null,
            {
                loadPerspectiveStats: async () => await reviewHogReviewsPerspectiveStatsRetrieve(currentProjectId()),
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
        savingSkillNames: [
            [] as string[],
            {
                setSkillSaving: (state, { skillName, saving }) =>
                    saving ? [...state, skillName] : state.filter((name) => name !== skillName),
            },
        ],
        viewedSkill: [
            // Kept through close so the drawer doesn't blank mid-animation; `skillDrawerOpen` gates visibility.
            null as ViewedSkill | null,
            {
                viewSkill: (_, { skill }) => skill,
            },
        ],
        skillDrawerOpen: [
            false,
            {
                viewSkill: () => true,
                closeSkillDrawer: () => false,
            },
        ],
        // The clicked list row: the drawer header renders from it instantly while the detail loads.
        openedReview: [
            null as ReviewRecentReviewApi | null,
            {
                openReviewDetail: (_, { review }) => review,
            },
        ],
        reviewDetail: {
            // Clear the previous review's detail so opening another row never flashes stale findings.
            openReviewDetail: () => null,
        },
        reviewDrawerOpen: [
            false,
            {
                openReviewDetail: () => true,
                closeReviewDrawer: () => false,
            },
        ],
        reviewDrawerTab: [
            'published' as ReviewDrawerTab,
            {
                setReviewDrawerTab: (_, { tab }) => tab,
                openReviewDetail: () => 'published' as ReviewDrawerTab,
            },
        ],
        expandedReviewIds: [
            [] as string[],
            {
                toggleReviewRowExpanded: (state, { reviewId }) =>
                    state.includes(reviewId) ? state.filter((id) => id !== reviewId) : [...state, reviewId],
            },
        ],
        recentReviewsPage: {
            // "Show fewer" collapses instantly from data already loaded; the listener's refetch
            // reconciles silently and breakpoint-drops any wider in-flight response (e.g. a poll).
            showFewerReviews: (state: ReviewRecentReviewsPageApi | null) =>
                state
                    ? {
                          ...state,
                          results: state.results.slice(0, REVIEWS_PAGE_SIZE),
                          has_more: state.has_more || state.results.length > REVIEWS_PAGE_SIZE,
                      }
                    : state,
        },
        // How many rows the review list asks for — grows by a page per "Show more".
        reviewsLimit: [
            REVIEWS_PAGE_SIZE as number,
            {
                showMoreReviews: (state) => Math.min(state + REVIEWS_PAGE_SIZE, MAX_REVIEWS_LIMIT),
                showFewerReviews: () => REVIEWS_PAGE_SIZE,
                // A different scope is a different list — start it compact again.
                setReviewsScope: () => REVIEWS_PAGE_SIZE,
                applyDefaultReviewsScope: () => REVIEWS_PAGE_SIZE,
            },
        ],
        // Drives the "Show more" button's loading state — the loader's own `loading` would also
        // flash on every 10s in-progress poll.
        reviewsExpanding: [
            false,
            {
                showMoreReviews: () => true,
                showFewerReviews: () => false,
                loadRecentReviewsSuccess: () => false,
                loadRecentReviewsFailure: () => false,
            },
        ],
        // Whose reviews the "recent reviews" block lists — mirrors the inbox's
        // "For you / Entire project" switch.
        reviewsScope: [
            ReviewHogReviewsListScope.Mine as ReviewHogReviewsListScope,
            { persist: true },
            {
                setReviewsScope: (_, { scope }) => scope,
                applyDefaultReviewsScope: (_, { scope }) => scope,
            },
        ],
        // Whether the user has explicitly picked a scope. Once true, the empty-list auto-default
        // no longer fires, so a deliberate choice of "For you" is respected even with zero reviews.
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
                // recentReviews/perspectiveStats stay null on failure and their sections render
                // skeletons while null — without these the skeletons are permanent, with no retry.
                loadRecentReviewsFailure: () => true,
                loadPerspectiveStatsFailure: () => true,
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
    }),

    selectors({
        recentReviews: [
            (s) => [s.recentReviewsPage],
            (recentReviewsPage): ReviewRecentReviewApi[] | null => recentReviewsPage?.results ?? null,
        ],
        moreReviewsAvailable: [
            (s) => [s.recentReviewsPage, s.reviewsLimit],
            (recentReviewsPage, reviewsLimit): boolean =>
                // At the API's ceiling the button must go away even though more rows exist —
                // offering it would send a limit the server rejects.
                (recentReviewsPage?.has_more ?? false) && reviewsLimit < MAX_REVIEWS_LIMIT,
        ],
        // Splits the detail's valid findings by the CURRENT threshold — a close-enough proxy for
        // what the run published (the run's own threshold snapshot isn't stored).
        reviewFindingsSplit: [
            (s) => [s.reviewDetail, s.settings],
            (
                reviewDetail: ReviewDetailApi | null,
                settings: ReviewUserSettingsApi | null
            ): ReviewFindingsSplit | null => {
                if (!reviewDetail) {
                    return null
                }
                const thresholdRank = REVIEW_PRIORITY_RANK[settings?.urgency_threshold ?? 'should_fix']
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
        // Poll while any review is running so the stage row moves; the disposable auto-pauses on
        // hidden tabs and is torn down on unmount.
        loadRecentReviewsSuccess: () => {
            if (values.recentReviews?.some((review) => review.in_progress)) {
                cache.disposables.add(() => {
                    const pollTimer = window.setInterval(
                        () => actions.loadRecentReviews(),
                        IN_PROGRESS_POLL_INTERVAL_MS
                    )
                    return () => clearInterval(pollTimer)
                }, 'inProgressPoll')
            } else {
                cache.disposables.dispose('inProgressPoll')
            }
            // No reviews of the user's own PRs: default to the whole project so the block isn't
            // empty — only until the user picks a scope themselves.
            if (
                !values.recentReviews?.length &&
                values.reviewsScope === ReviewHogReviewsListScope.Mine &&
                !values.hasUserChosenReviewsScope
            ) {
                actions.applyDefaultReviewsScope(ReviewHogReviewsListScope.Everyone)
            }
        },
        setReviewsScope: () => actions.loadRecentReviews(),
        applyDefaultReviewsScope: () => actions.loadRecentReviews(),
        showMoreReviews: () => actions.loadRecentReviews(),
        showFewerReviews: () => actions.loadRecentReviews(),
        loadAll: () => {
            actions.loadSettings()
            actions.loadPerspectives()
            actions.loadBlindSpots()
            actions.loadValidators()
            actions.loadRecentReviews()
            actions.loadPerspectiveStats()
        },
        updateSettingsFailure: () => {
            // The global loaders toast already surfaced the error; just reconcile the optimistic state.
            actions.loadSettings()
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
        blockSingleActiveDeactivation: ({ kindLabel }) => {
            lemonToast.info(`One ${kindLabel} always runs — switch by selecting another one`)
        },
        openReviewDetail: ({ review }) => {
            actions.loadReviewDetail(review.id)
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
    actionToUrl(({ values }) => ({
        setReviewsScope: (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => [
            router.values.location.pathname,
            {
                ...router.values.searchParams,
                reviews_scope: values.reviewsScope === ReviewHogReviewsListScope.Mine ? undefined : values.reviewsScope,
            },
            router.values.hashParams,
            { replace: true },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.codeReview()]: (_, searchParams) => {
            const parsed = searchParams.reviews_scope
            if (
                (parsed === ReviewHogReviewsListScope.Mine || parsed === ReviewHogReviewsListScope.Everyone) &&
                parsed !== values.reviewsScope
            ) {
                actions.setReviewsScope(parsed)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAll()
    }),
])
