import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    PatchedReviewBlindSpotsConfigSelectApi,
    PatchedReviewPerspectiveConfigUpdateApi,
    PatchedReviewUserSettingsApi,
    PatchedReviewValidatorConfigSelectApi,
    ReviewBlindSpotsConfigApi,
    ReviewDetailApi,
    ReviewHogReviewsListParams,
    ReviewPerspectiveConfigApi,
    ReviewPerspectiveStatsApi,
    ReviewRecentReviewsPageApi,
    ReviewTriggerRequestApi,
    ReviewTriggerResponseApi,
    ReviewUserSettingsApi,
    ReviewValidatorConfigApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getReviewHogBlindSpotsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/blind_spots/`
}

/**
 * List the `review-hog-blind-spots-*` skills visible to the requesting user — the canonical skill plus the customs they authored — flagging the one active for them. The canonical skill is auto-seeded active on the first read; a custom skill the user has not selected shows as inactive.
 * @summary List blind-spots skills and which one is active
 */
export const reviewHogBlindSpotsList = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewBlindSpotsConfigApi[]> => {
    return apiMutator<ReviewBlindSpotsConfigApi[]>(getReviewHogBlindSpotsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogBlindSpotsPartialUpdateUrl = (projectId: string, skillName: string) => {
    return `/api/projects/${projectId}/review_hog/blind_spots/${skillName}/`
}

/**
 * Make a `review-hog-blind-spots-*` skill the single sweep that runs on the requesting user's PR reviews, switching the user's other blind-spots skills off in the same call. Only skills visible to the user — the canonical plus the customs they authored — can be selected; anything else 404s. Upserts the per-user config row, so selecting a freshly authored custom skill works in one call.
 * @summary Select the active blind-spots skill
 */
export const reviewHogBlindSpotsPartialUpdate = async (
    projectId: string,
    skillName: string,
    patchedReviewBlindSpotsConfigSelectApi?: PatchedReviewBlindSpotsConfigSelectApi,
    options?: RequestInit
): Promise<ReviewBlindSpotsConfigApi> => {
    return apiMutator<ReviewBlindSpotsConfigApi>(getReviewHogBlindSpotsPartialUpdateUrl(projectId, skillName), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReviewBlindSpotsConfigSelectApi),
    })
}

export const getReviewHogPerspectivesListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/perspectives/`
}

/**
 * List the `review-hog-perspective-*` skills visible to the requesting user — the canonical perspectives plus the customs they authored — joined with their enable state. The 3 canonical perspectives are auto-seeded enabled on the first read; a custom perspective the user has not switched on shows as disabled.
 * @summary List review perspectives and their enablement
 */
export const reviewHogPerspectivesList = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewPerspectiveConfigApi[]> => {
    return apiMutator<ReviewPerspectiveConfigApi[]>(getReviewHogPerspectivesListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogPerspectivesPartialUpdateUrl = (projectId: string, skillName: string) => {
    return `/api/projects/${projectId}/review_hog/perspectives/${skillName}/`
}

/**
 * Toggle whether a `review-hog-perspective-*` skill runs on the requesting user's PR reviews. Only skills visible to the user — the canonicals plus the customs they authored — can be toggled; anything else 404s. Upserts the per-user config row, so enabling a freshly authored custom perspective works in one call. Rejected if it would leave the user with no enabled perspective.
 * @summary Enable or disable a review perspective
 */
export const reviewHogPerspectivesPartialUpdate = async (
    projectId: string,
    skillName: string,
    patchedReviewPerspectiveConfigUpdateApi?: PatchedReviewPerspectiveConfigUpdateApi,
    options?: RequestInit
): Promise<ReviewPerspectiveConfigApi> => {
    return apiMutator<ReviewPerspectiveConfigApi>(getReviewHogPerspectivesPartialUpdateUrl(projectId, skillName), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReviewPerspectiveConfigUpdateApi),
    })
}

export const getReviewHogReviewsListUrl = (projectId: string, params?: ReviewHogReviewsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/review_hog/reviews/?${stringifiedParams}`
        : `/api/projects/${projectId}/review_hog/reviews/`
}

/**
 * Recent ReviewHog reviews on this project: actively running reviews first (with the in-flight turn's stage), then the most recent completed ones — at most `limit` rows (default 5), plus `has_more` for whether a larger `limit` would reveal more. By default only the requesting user's reviews; `scope=everyone` lists every review on the project.
 * @summary List recent reviews
 */
export const reviewHogReviewsList = async (
    projectId: string,
    params?: ReviewHogReviewsListParams,
    options?: RequestInit
): Promise<ReviewRecentReviewsPageApi> => {
    return apiMutator<ReviewRecentReviewsPageApi>(getReviewHogReviewsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogReviewsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/review_hog/reviews/${id}/`
}

/**
 * One completed ReviewHog review on this project, with the latest turn's validated findings, the findings the validator dismissed (and why), and the review body published to GitHub. Project-wide, so reviews listed under `scope=everyone` can be opened too.
 * @summary Retrieve one review's detail
 */
export const reviewHogReviewsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ReviewDetailApi> => {
    return apiMutator<ReviewDetailApi>(getReviewHogReviewsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogReviewsPerspectiveStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/reviews/perspective_stats/`
}

/**
 * How many findings each review skill (perspective or blind-spot sweep) raised across the requesting user's recent completed reviews, and how many of those the validator kept vs dismissed.
 * @summary Perspective effectiveness stats
 */
export const reviewHogReviewsPerspectiveStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewPerspectiveStatsApi> => {
    return apiMutator<ReviewPerspectiveStatsApi>(getReviewHogReviewsPerspectiveStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogReviewsTriggerCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/reviews/trigger/`
}

/**
 * Start a ReviewHog review of any pull request the project's GitHub App installation can access, and publish it back to the PR. The requesting user is the review's acting user: their enabled perspectives, blind-spot check, validator, and urgency threshold drive the run, and it appears under their recent reviews. Nonexistent, closed, and fork PRs are rejected synchronously; a PR whose current commit already has a published review returns 'already_reviewed' without starting a run, and triggering a PR whose review is currently running joins the in-flight run. Otherwise non-blocking: returns the Temporal workflow id immediately while the review runs in the worker.
 * @summary Start a review of a pull request
 */
export const reviewHogReviewsTriggerCreate = async (
    projectId: string,
    reviewTriggerRequestApi: ReviewTriggerRequestApi,
    options?: RequestInit
): Promise<ReviewTriggerResponseApi> => {
    return apiMutator<ReviewTriggerResponseApi>(getReviewHogReviewsTriggerCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewTriggerRequestApi),
    })
}

export const getReviewHogSettingsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/settings/`
}

/**
 * Fetch the requesting user's ReviewHog settings for this project, creating the row with defaults on first read.
 * @summary Get the user's ReviewHog settings
 */
export const reviewHogSettingsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewUserSettingsApi> => {
    return apiMutator<ReviewUserSettingsApi>(getReviewHogSettingsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogSettingsPartialUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/settings/`
}

/**
 * Partially update the requesting user's ReviewHog settings for this project. Only the provided fields change.
 * @summary Update the user's ReviewHog settings
 */
export const reviewHogSettingsPartialUpdate = async (
    projectId: string,
    patchedReviewUserSettingsApi?: NonReadonly<PatchedReviewUserSettingsApi>,
    options?: RequestInit
): Promise<ReviewUserSettingsApi> => {
    return apiMutator<ReviewUserSettingsApi>(getReviewHogSettingsPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReviewUserSettingsApi),
    })
}

export const getReviewHogValidatorsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/validators/`
}

/**
 * List the `review-hog-validation-*` skills visible to the requesting user — the canonical validator plus the customs they authored — flagging the one active for them. The canonical validator is auto-seeded active on the first read; a custom validator the user has not selected shows as inactive.
 * @summary List review validators and which one is active
 */
export const reviewHogValidatorsList = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewValidatorConfigApi[]> => {
    return apiMutator<ReviewValidatorConfigApi[]>(getReviewHogValidatorsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogValidatorsPartialUpdateUrl = (projectId: string, skillName: string) => {
    return `/api/projects/${projectId}/review_hog/validators/${skillName}/`
}

/**
 * Make a `review-hog-validation-*` skill the single validator that runs on the requesting user's PR reviews, switching the user's other validators off in the same call. Only skills visible to the user — the canonical plus the customs they authored — can be selected; anything else 404s. Upserts the per-user config row, so selecting a freshly authored custom validator works in one call.
 * @summary Select the active review validator
 */
export const reviewHogValidatorsPartialUpdate = async (
    projectId: string,
    skillName: string,
    patchedReviewValidatorConfigSelectApi?: PatchedReviewValidatorConfigSelectApi,
    options?: RequestInit
): Promise<ReviewValidatorConfigApi> => {
    return apiMutator<ReviewValidatorConfigApi>(getReviewHogValidatorsPartialUpdateUrl(projectId, skillName), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReviewValidatorConfigSelectApi),
    })
}
