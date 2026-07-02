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
    ReviewPerspectiveConfigApi,
    ReviewUserSettingsApi,
    ReviewValidatorConfigApi,
} from './api.schemas'

export const getReviewHogBlindSpotsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/blind_spots/`
}

/**
 * List every `review-hog-blind-spots-*` skill on this project, flagging the one active for the requesting user. The canonical skill is auto-seeded active on the first read; a custom skill the user has not selected shows as inactive.
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
 * Make a `review-hog-blind-spots-*` skill the single sweep that runs on the requesting user's PR reviews, switching the user's other blind-spots skills off in the same call. Upserts the per-user config row, so selecting a freshly authored custom skill works in one call.
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
 * List every `review-hog-perspective-*` skill on this project joined with the requesting user's enable state. The 3 canonical perspectives are auto-seeded enabled on the first read; a custom perspective the user has not switched on shows as disabled.
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
 * Toggle whether a `review-hog-perspective-*` skill runs on the requesting user's PR reviews. Upserts the per-user config row, so enabling a freshly authored custom perspective works in one call. Rejected if it would leave the user with no enabled perspective.
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
    patchedReviewUserSettingsApi?: PatchedReviewUserSettingsApi,
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
 * List every `review-hog-validation-*` skill on this project, flagging the one active for the requesting user. The canonical validator is auto-seeded active on the first read; a custom validator the user has not selected shows as inactive.
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
 * Make a `review-hog-validation-*` skill the single validator that runs on the requesting user's PR reviews, switching the user's other validators off in the same call. Upserts the per-user config row, so selecting a freshly authored custom validator works in one call.
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
