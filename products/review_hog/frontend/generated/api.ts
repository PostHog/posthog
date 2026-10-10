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
    PatchedReviewInstallationClaimUpdateApi,
    PatchedReviewPerspectiveConfigUpdateApi,
    PatchedReviewProjectSettingsApi,
    PatchedReviewResolutionConfigSelectApi,
    PatchedReviewUserSettingsApi,
    PatchedReviewValidatorConfigSelectApi,
    ReviewBlindSpotsConfigApi,
    ReviewDetailApi,
    ReviewHogRepositoryOverviewRetrieveParams,
    ReviewHogReviewsListParams,
    ReviewHogReviewsPerspectiveStatsRetrieveParams,
    ReviewInstallationClaimApi,
    ReviewInstallationClaimCreateApi,
    ReviewPerspectiveConfigApi,
    ReviewPerspectiveStatsApi,
    ReviewProjectSettingsApi,
    ReviewRecentReviewsPageApi,
    ReviewRepositoryApi,
    ReviewRepositoryChoiceApi,
    ReviewRepositoryChoiceWriteApi,
    ReviewRepositoryChoiceWriteResponseApi,
    ReviewRepositoryOverviewApi,
    ReviewRepositoryPersonRequestApi,
    ReviewRepositoryWriteApi,
    ReviewRepositoryWriteResponseApi,
    ReviewResolutionConfigApi,
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

export const getReviewHogInstallationClaimsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/installation_claims/`
}

/**
 * Which repositories of each connected GitHub installation this project reviews.
 *
 * Project members can read the claims. Only project admins can change them, and every change goes
 * to the activity log. The project settings response lists every connected installation, also the
 * ones without a claim.
 */
export const reviewHogInstallationClaimsList = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewInstallationClaimApi[]> => {
    return apiMutator<ReviewInstallationClaimApi[]>(getReviewHogInstallationClaimsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogInstallationClaimsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/installation_claims/`
}

/**
 * Choose which repositories of a connected GitHub installation this project reviews.
 * @summary Claim a GitHub installation
 */
export const reviewHogInstallationClaimsCreate = async (
    projectId: string,
    reviewInstallationClaimCreateApi: ReviewInstallationClaimCreateApi,
    options?: RequestInit
): Promise<ReviewInstallationClaimApi> => {
    return apiMutator<ReviewInstallationClaimApi>(getReviewHogInstallationClaimsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewInstallationClaimCreateApi),
    })
}

export const getReviewHogInstallationClaimsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/review_hog/installation_claims/${id}/`
}

/**
 * Switch between all repositories and only selected repositories. Switching to selected removes the exceptions of the repositories that leave this project. Personal choices stay.
 * @summary Change a GitHub installation claim
 */
export const reviewHogInstallationClaimsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedReviewInstallationClaimUpdateApi?: PatchedReviewInstallationClaimUpdateApi,
    options?: RequestInit
): Promise<ReviewInstallationClaimApi> => {
    return apiMutator<ReviewInstallationClaimApi>(getReviewHogInstallationClaimsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReviewInstallationClaimUpdateApi),
    })
}

export const getReviewHogInstallationClaimsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/review_hog/installation_claims/${id}/`
}

/**
 * Remove the claim, so this project reviews no repository of the installation. Its selected repositories and exceptions there are removed too. Personal choices stay.
 * @summary Stop reviewing a GitHub installation
 */
export const reviewHogInstallationClaimsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getReviewHogInstallationClaimsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
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

export const getReviewHogProjectSettingsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/project_settings/`
}

/**
 * The project rule for automatic Flash reviews, bot pull requests, the Full review defaults, and the connected GitHub installations.
 * @summary Get the project's ReviewHog rule
 */
export const reviewHogProjectSettingsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewProjectSettingsApi> => {
    return apiMutator<ReviewProjectSettingsApi>(getReviewHogProjectSettingsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogProjectSettingsPartialUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/project_settings/`
}

/**
 * Partially update the project rule. Only the provided fields change. Project admins only.
 * @summary Update the project's ReviewHog rule
 */
export const reviewHogProjectSettingsPartialUpdate = async (
    projectId: string,
    patchedReviewProjectSettingsApi?: NonReadonly<PatchedReviewProjectSettingsApi>,
    options?: RequestInit
): Promise<ReviewProjectSettingsApi> => {
    return apiMutator<ReviewProjectSettingsApi>(getReviewHogProjectSettingsPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReviewProjectSettingsApi),
    })
}

export const getReviewHogProjectSettingsPeopleCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/project_settings/people/`
}

/**
 * Add a project member to the project rule's 'listed' or 'excepted' list. Project admins only.
 * @summary Add a person to a project rule list
 */
export const reviewHogProjectSettingsPeopleCreate = async (
    projectId: string,
    reviewRepositoryPersonRequestApi: ReviewRepositoryPersonRequestApi,
    options?: RequestInit
): Promise<ReviewProjectSettingsApi> => {
    return apiMutator<ReviewProjectSettingsApi>(getReviewHogProjectSettingsPeopleCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewRepositoryPersonRequestApi),
    })
}

export const getReviewHogProjectSettingsPeopleDestroyUrl = (projectId: string, personId: string) => {
    return `/api/projects/${projectId}/review_hog/project_settings/people/${personId}/`
}

/**
 * Remove one entry from the project rule's 'listed' or 'excepted' list. Project admins only.
 * @summary Remove a person from a project rule list
 */
export const reviewHogProjectSettingsPeopleDestroy = async (
    projectId: string,
    personId: string,
    options?: RequestInit
): Promise<ReviewProjectSettingsApi> => {
    return apiMutator<ReviewProjectSettingsApi>(getReviewHogProjectSettingsPeopleDestroyUrl(projectId, personId), {
        ...options,
        method: 'DELETE',
    })
}

export const getReviewHogRepositoriesListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/repositories/`
}

/**
 * The repositories this project has settings for: selected repositories and repository exceptions.
 *
 * Project members can read them. Only project admins can change them, and every change goes to the
 * activity log. A repository has settings in one project at most.
 */
export const reviewHogRepositoriesList = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewRepositoryApi[]> => {
    return apiMutator<ReviewRepositoryApi[]>(getReviewHogRepositoriesListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogRepositoriesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/repositories/`
}

/**
 * Include a repository into this project, remove it, or set or clear its exception. Only the provided fields change. Including a repository that another project's 'all repositories' claim covers takes it from that project; the response names it.
 * @summary Save a repository's settings
 */
export const reviewHogRepositoriesCreate = async (
    projectId: string,
    reviewRepositoryWriteApi: ReviewRepositoryWriteApi,
    options?: RequestInit
): Promise<ReviewRepositoryWriteResponseApi> => {
    return apiMutator<ReviewRepositoryWriteResponseApi>(getReviewHogRepositoriesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewRepositoryWriteApi),
    })
}

export const getReviewHogRepositoriesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/review_hog/repositories/${id}/`
}

/**
 * Remove the repository from this project and clear its exception and lists. With an 'all repositories' claim the repository stays in the project and follows the project rule.
 * @summary Remove a repository's settings
 */
export const reviewHogRepositoriesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getReviewHogRepositoriesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getReviewHogRepositoriesPeopleCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/review_hog/repositories/${id}/people/`
}

/**
 * Add a project member to the 'listed' or 'excepted' list of the repository exception.
 * @summary Add a person to a repository exception list
 */
export const reviewHogRepositoriesPeopleCreate = async (
    projectId: string,
    id: string,
    reviewRepositoryPersonRequestApi: ReviewRepositoryPersonRequestApi,
    options?: RequestInit
): Promise<ReviewRepositoryApi> => {
    return apiMutator<ReviewRepositoryApi>(getReviewHogRepositoriesPeopleCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewRepositoryPersonRequestApi),
    })
}

export const getReviewHogRepositoriesPeopleDestroyUrl = (projectId: string, id: string, personId: string) => {
    return `/api/projects/${projectId}/review_hog/repositories/${id}/people/${personId}/`
}

/**
 * Remove one entry from the 'listed' or 'excepted' list of the repository exception.
 * @summary Remove a person from a repository exception list
 */
export const reviewHogRepositoriesPeopleDestroy = async (
    projectId: string,
    id: string,
    personId: string,
    options?: RequestInit
): Promise<ReviewRepositoryApi> => {
    return apiMutator<ReviewRepositoryApi>(getReviewHogRepositoriesPeopleDestroyUrl(projectId, id, personId), {
        ...options,
        method: 'DELETE',
    })
}

export const getReviewHogRepositoryChoicesListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/repository_choices/`
}

/**
 * The requesting user's own automatic review choices for repositories of this project.
 *
 * Any project member can manage their own choices. A choice stores only what differs from what the
 * user inherits, so picking the inherited value clears it.
 */
export const reviewHogRepositoryChoicesList = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewRepositoryChoiceApi[]> => {
    return apiMutator<ReviewRepositoryChoiceApi[]>(getReviewHogRepositoryChoicesListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogRepositoryChoicesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/repository_choices/`
}

/**
 * Set the requesting user's own automatic review for their pull requests in one repository. It wins over their default and over the repository and project rules.
 * @summary Set my choice for a repository
 */
export const reviewHogRepositoryChoicesCreate = async (
    projectId: string,
    reviewRepositoryChoiceWriteApi: ReviewRepositoryChoiceWriteApi,
    options?: RequestInit
): Promise<ReviewRepositoryChoiceWriteResponseApi> => {
    return apiMutator<ReviewRepositoryChoiceWriteResponseApi>(getReviewHogRepositoryChoicesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewRepositoryChoiceWriteApi),
    })
}

export const getReviewHogRepositoryChoicesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/review_hog/repository_choices/${id}/`
}

/**
 * Clear the requesting user's own choice for one repository, so their default applies again.
 * @summary Clear my choice for a repository
 */
export const reviewHogRepositoryChoicesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getReviewHogRepositoryChoicesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getReviewHogRepositoryOverviewRetrieveUrl = (
    projectId: string,
    params: ReviewHogRepositoryOverviewRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/review_hog/repository_overview/?${stringifiedParams}`
        : `/api/projects/${projectId}/review_hog/repository_overview/`
}

/**
 * Every repository the GitHub installation can see, with the project that reviews it, this project's settings, the requesting user's choice, and the automatic review the requesting user gets.
 * @summary List the repositories of a GitHub installation with their review settings
 */
export const reviewHogRepositoryOverviewRetrieve = async (
    projectId: string,
    params: ReviewHogRepositoryOverviewRetrieveParams,
    options?: RequestInit
): Promise<ReviewRepositoryOverviewApi> => {
    return apiMutator<ReviewRepositoryOverviewApi>(getReviewHogRepositoryOverviewRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogResolutionListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/resolution/`
}

/**
 * List the `review-hog-resolution-*` skills visible to the requesting user — the canonical criteria plus the customs they authored — flagging the one active for them. The canonical skill is auto-seeded active on the first read; a custom skill the user has not selected shows as inactive.
 * @summary List resolution criteria and which one is active
 */
export const reviewHogResolutionList = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewResolutionConfigApi[]> => {
    return apiMutator<ReviewResolutionConfigApi[]>(getReviewHogResolutionListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogResolutionPartialUpdateUrl = (projectId: string, skillName: string) => {
    return `/api/projects/${projectId}/review_hog/resolution/${skillName}/`
}

/**
 * Make a `review-hog-resolution-*` skill the single criteria the resolution stage applies on the requesting user's PRs, switching the user's other resolution skills off in the same call. Only skills visible to the user — the canonical plus the customs they authored — can be selected; anything else 404s. Upserts the per-user config row, so selecting a freshly authored custom skill works in one call.
 * @summary Select the active resolution criteria
 */
export const reviewHogResolutionPartialUpdate = async (
    projectId: string,
    skillName: string,
    patchedReviewResolutionConfigSelectApi?: PatchedReviewResolutionConfigSelectApi,
    options?: RequestInit
): Promise<ReviewResolutionConfigApi> => {
    return apiMutator<ReviewResolutionConfigApi>(getReviewHogResolutionPartialUpdateUrl(projectId, skillName), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReviewResolutionConfigSelectApi),
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

export const getReviewHogReviewsPerspectiveStatsRetrieveUrl = (
    projectId: string,
    params?: ReviewHogReviewsPerspectiveStatsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/review_hog/reviews/perspective_stats/?${stringifiedParams}`
        : `/api/projects/${projectId}/review_hog/reviews/perspective_stats/`
}

/**
 * How many findings each review skill (perspective or blind-spot sweep) raised across the recent completed reviews in scope — the requesting user's by default, every review on this project with `scope=everyone`, the user's own last Deep reviews with `scope=own_deep` — and how many of those the validator kept vs dismissed.
 * @summary Perspective effectiveness stats
 */
export const reviewHogReviewsPerspectiveStatsRetrieve = async (
    projectId: string,
    params?: ReviewHogReviewsPerspectiveStatsRetrieveParams,
    options?: RequestInit
): Promise<ReviewPerspectiveStatsApi> => {
    return apiMutator<ReviewPerspectiveStatsApi>(getReviewHogReviewsPerspectiveStatsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getReviewHogReviewsTriggerCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/review_hog/reviews/trigger/`
}

/**
 * Start a ReviewHog review of any pull request the project's GitHub App installation can access, and publish it back to the PR. The requesting user is the review's acting user: their enabled perspectives, blind-spot check, validator, and urgency threshold drive the run, and it appears under their recent reviews. Resolution writes to the branch only when the pull request owner opted in, whoever asks. `run_mode` picks the variant: a review (which chains the resolution stage per the owner's resolve_comments setting), a review without resolving, resolution only, or a lower-cost Flash review that never resolves comments and is refused after a published Full review. Nonexistent, closed, and fork PRs are rejected synchronously; a PR whose current commit already has a published review returns 'already_reviewed' without starting a run (resolve_only skips that check — settling threads on a reviewed head is its whole point), and triggering a PR whose run is currently in flight joins that run. Otherwise non-blocking: returns the Temporal workflow id immediately while the run executes in the worker.
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
 * Fetch the requesting user's effective ReviewHog preferences for this project, and where each value comes from.
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
 * Partially update the requesting user's ReviewHog preferences for this project. Only the provided fields change. A value equal to the inherited one clears the user's own value.
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
