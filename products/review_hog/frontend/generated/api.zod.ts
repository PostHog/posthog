/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Make a `review-hog-blind-spots-*` skill the single sweep that runs on the requesting user's PR reviews, switching the user's other blind-spots skills off in the same call. Only skills visible to the user — the canonical plus the customs they authored — can be selected; anything else 404s. Upserts the per-user config row, so selecting a freshly authored custom skill works in one call.
 * @summary Select the active blind-spots skill
 */
export const ReviewHogBlindSpotsPartialUpdateBody = /* @__PURE__ */ zod.object({
    active: zod
        .boolean()
        .optional()
        .describe(
            "Set true to make this the single blind-spots skill that runs on the user's PR reviews. Only true is accepted — the blind-spot check is single-active, so you switch by selecting a different skill, not by deactivating the current one."
        ),
})

/**
 * Choose which repositories of a connected GitHub installation this project reviews.
 * @summary Claim a GitHub installation
 */
export const reviewHogInstallationClaimsCreateBodyInstallationIdMax = 64

export const ReviewHogInstallationClaimsCreateBody = /* @__PURE__ */ zod.object({
    installation_id: zod
        .string()
        .max(reviewHogInstallationClaimsCreateBodyInstallationIdMax)
        .describe('The GitHub App installation id.'),
    scope: zod
        .enum(['all', 'selected'])
        .describe('\* `all` - All repositories\n\* `selected` - Only selected repositories')
        .describe(
            "'all' reviews every repository of the installation that no other project selected. At most one project per installation can choose it. 'selected' reviews only selected repositories.\n\n\* `all` - All repositories\n\* `selected` - Only selected repositories"
        ),
})

/**
 * Switch between all repositories and only selected repositories. Switching to selected removes the exceptions of the repositories that leave this project. Personal choices stay.
 * @summary Change a GitHub installation claim
 */
export const ReviewHogInstallationClaimsPartialUpdateBody = /* @__PURE__ */ zod.object({
    scope: zod
        .enum(['all', 'selected'])
        .describe('\* `all` - All repositories\n\* `selected` - Only selected repositories')
        .optional()
        .describe(
            "'all' or 'selected'. Switching to 'selected' removes the exceptions of the repositories that leave the project.\n\n\* `all` - All repositories\n\* `selected` - Only selected repositories"
        ),
})

/**
 * Toggle whether a `review-hog-perspective-*` skill runs on the requesting user's PR reviews. Only skills visible to the user — the canonicals plus the customs they authored — can be toggled; anything else 404s. Upserts the per-user config row, so enabling a freshly authored custom perspective works in one call. Rejected if it would leave the user with no enabled perspective.
 * @summary Enable or disable a review perspective
 */
export const ReviewHogPerspectivesPartialUpdateBody = /* @__PURE__ */ zod.object({
    enabled: zod
        .boolean()
        .optional()
        .describe("Set true to run this perspective on the user's PR reviews, false to stop running it."),
})

/**
 * Partially update the project rule. Only the provided fields change. Project admins only.
 * @summary Update the project's ReviewHog rule
 */
export const ReviewHogProjectSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    flash_for: zod
        .enum(['everyone', 'listed', 'off'])
        .describe(
            '\* `everyone` - Automatic Flash for everyone\n\* `listed` - Automatic Flash for these people\n\* `off` - Automatic Flash opt-in only'
        )
        .optional()
        .describe(
            "Who gets automatic Flash reviews in the repositories this project reviews: 'everyone' (except the excepted people), 'listed' (only the listed people), or 'off' (only people who opt in, the default). A repository exception or a person's own choice wins over it.\n\n\* `everyone` - Automatic Flash for everyone\n\* `listed` - Automatic Flash for these people\n\* `off` - Automatic Flash opt-in only"
        ),
    bot_prs: zod
        .enum(['skip', 'run'])
        .describe('\* `skip` - Not reviewed\n\* `run` - Automatic Flash')
        .optional()
        .describe(
            "Pull requests from bots, and from authors who are not project members, in every repository this project reviews: 'skip' (not reviewed, the default) or 'run' (automatic Flash that runs as the person who connected GitHub, with default settings and no changes to the pull request).\n\n\* `skip` - Not reviewed\n\* `run` - Automatic Flash"
        ),
    urgency_threshold: zod
        .enum(['consider', 'should_fix', 'must_fix'])
        .describe('\* `consider` - Consider (all)\n\* `should_fix` - Should fix\n\* `must_fix` - Must fix')
        .optional()
        .describe(
            "Project default for the minimum priority a Full review publishes: 'consider' (all, the built-in default), 'should_fix', or 'must_fix'. A person's own value wins.\n\n\* `consider` - Consider (all)\n\* `should_fix` - Should fix\n\* `must_fix` - Must fix"
        ),
    celebrate_clean_reviews: zod
        .boolean()
        .optional()
        .describe(
            "Project default for the image in a Full review that finds nothing to raise. On by default. A person's own value wins."
        ),
})

/**
 * Add a project member to the project rule's 'listed' or 'excepted' list. Project admins only.
 * @summary Add a person to a project rule list
 */
export const ReviewHogProjectSettingsPeopleCreateBody = /* @__PURE__ */ zod.object({
    user_id: zod.number().describe('Id of the project member to add. Must be an active member.'),
    kind: zod
        .enum(['listed', 'excepted'])
        .describe('\* `listed` - Listed\n\* `excepted` - Excepted')
        .describe(
            "Which list to add the person to: 'listed' or 'excepted'.\n\n\* `listed` - Listed\n\* `excepted` - Excepted"
        ),
})

/**
 * Include a repository into this project, remove it, or set or clear its exception. Only the provided fields change. Including a repository that another project's 'all repositories' claim covers takes it from that project; the response names it.
 * @summary Save a repository's settings
 */
export const reviewHogRepositoriesCreateBodyInstallationIdMax = 64

export const reviewHogRepositoriesCreateBodyFullNameMax = 200

export const ReviewHogRepositoriesCreateBody = /* @__PURE__ */ zod.object({
    installation_id: zod
        .string()
        .max(reviewHogRepositoriesCreateBodyInstallationIdMax)
        .describe('The GitHub App installation that sees the repository, from the overview.'),
    full_name: zod
        .string()
        .max(reviewHogRepositoriesCreateBodyFullNameMax)
        .describe("GitHub repository in 'owner\/name' form, spelled as GitHub returns it."),
    github_repo_id: zod
        .number()
        .min(1)
        .optional()
        .describe("GitHub's id of the repository, from the overview. Keeps renames."),
    selected: zod
        .boolean()
        .optional()
        .describe(
            "True includes the repository into this project, also when another project takes all repositories of the installation. False removes it; with an 'only selected' claim its exception goes too."
        ),
    flash_for: zod
        .union([
            zod
                .enum(['everyone', 'listed', 'off'])
                .describe(
                    '\* `everyone` - Automatic Flash for everyone\n\* `listed` - Automatic Flash for these people\n\* `off` - Automatic Flash opt-in only'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            "The repository exception: 'everyone', 'listed', or 'off'. Null clears it, so the repository follows the project rule again. Omit it to keep the current value.\n\n\* `everyone` - Automatic Flash for everyone\n\* `listed` - Automatic Flash for these people\n\* `off` - Automatic Flash opt-in only"
        ),
})

/**
 * Add a project member to the 'listed' or 'excepted' list of the repository exception.
 * @summary Add a person to a repository exception list
 */
export const ReviewHogRepositoriesPeopleCreateBody = /* @__PURE__ */ zod.object({
    user_id: zod.number().describe('Id of the project member to add. Must be an active member.'),
    kind: zod
        .enum(['listed', 'excepted'])
        .describe('\* `listed` - Listed\n\* `excepted` - Excepted')
        .describe(
            "Which list to add the person to: 'listed' or 'excepted'.\n\n\* `listed` - Listed\n\* `excepted` - Excepted"
        ),
})

/**
 * Set the requesting user's own automatic review for their pull requests in one repository. It wins over their default and over the repository and project rules.
 * @summary Set my choice for a repository
 */
export const reviewHogRepositoryChoicesCreateBodyInstallationIdMax = 64

export const reviewHogRepositoryChoicesCreateBodyFullNameMax = 200

export const ReviewHogRepositoryChoicesCreateBody = /* @__PURE__ */ zod.object({
    installation_id: zod
        .string()
        .max(reviewHogRepositoryChoicesCreateBodyInstallationIdMax)
        .describe('The GitHub App installation.'),
    full_name: zod
        .string()
        .max(reviewHogRepositoryChoicesCreateBodyFullNameMax)
        .describe("GitHub repository in 'owner\/name' form."),
    github_repo_id: zod.number().min(1).optional().describe("GitHub's repository id."),
    mode: zod
        .enum(['flash', 'off'])
        .describe('\* `flash` - Flash\n\* `off` - Off')
        .describe(
            "The requesting user's own automatic review for their pull requests in this repository: 'flash' or 'off'. A value equal to what the user inherits clears the choice instead.\n\n\* `flash` - Flash\n\* `off` - Off"
        ),
})

/**
 * Make a `review-hog-resolution-*` skill the single criteria the resolution stage applies on the requesting user's PRs, switching the user's other resolution skills off in the same call. Only skills visible to the user — the canonical plus the customs they authored — can be selected; anything else 404s. Upserts the per-user config row, so selecting a freshly authored custom skill works in one call.
 * @summary Select the active resolution criteria
 */
export const ReviewHogResolutionPartialUpdateBody = /* @__PURE__ */ zod.object({
    active: zod
        .boolean()
        .optional()
        .describe(
            "Set true to make these the single resolution criteria applied on the user's PRs. Only true is accepted — resolution criteria are single-active, so you switch by selecting a different skill, not by deactivating the current one."
        ),
})

/**
 * Start a ReviewHog review of any pull request the project's GitHub App installation can access, and publish it back to the PR. The requesting user is the review's acting user: their enabled perspectives, blind-spot check, validator, and urgency threshold drive the run, and it appears under their recent reviews. Resolution writes to the branch only when the pull request owner opted in, whoever asks. `run_mode` picks the variant: a review (which chains the resolution stage per the owner's resolve_comments setting), a review without resolving, resolution only, or a lower-cost Flash review that never resolves comments and is refused after a published Full review. Nonexistent, closed, and fork PRs are rejected synchronously; a PR whose current commit already has a published review returns 'already_reviewed' without starting a run (resolve_only skips that check — settling threads on a reviewed head is its whole point), and triggering a PR whose run is currently in flight joins that run. Otherwise non-blocking: returns the Temporal workflow id immediately while the run executes in the worker.
 * @summary Start a review of a pull request
 */
export const reviewHogReviewsTriggerCreateBodyRunModeDefault = `review`

export const ReviewHogReviewsTriggerCreateBody = /* @__PURE__ */ zod.object({
    pr_url: zod
        .string()
        .describe(
            "GitHub pull request URL to review, e.g. 'https:\/\/github.com\/PostHog\/posthog.com\/pull\/123'. The repository must be accessible to the project's GitHub App installation."
        ),
    run_mode: zod
        .enum(['review', 'review_only', 'resolve_only', 'flash'])
        .describe(
            '\* `review` - Review\n\* `review_only` - Review only\n\* `resolve_only` - Resolve only\n\* `flash` - Flash'
        )
        .default(reviewHogReviewsTriggerCreateBodyRunModeDefault)
        .describe(
            "What to run on the pull request. 'review' (default) reviews it and, when the pull request owner's resolve_comments setting is on, chains the resolution stage; 'review_only' reviews without resolving regardless of that setting; 'resolve_only' skips the review and only runs the resolution stage on the PR's existing unresolved review threads, which needs the owner's opt-in; 'flash' uses a lower-cost model for the review passes and validation, never resolves comments, and is refused once the PR has a published Full review. The owner is the PR's author, or the Inbox reviewer of a pull request the PostHog app opened.\n\n\* `review` - Review\n\* `review_only` - Review only\n\* `resolve_only` - Resolve only\n\* `flash` - Flash"
        ),
})

/**
 * Partially update the requesting user's ReviewHog preferences for this project. Only the provided fields change. A value equal to the inherited one clears the user's own value.
 * @summary Update the user's ReviewHog settings
 */
export const ReviewHogSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    default_review_mode: zod
        .enum(['follow', 'flash', 'off'])
        .describe('\* `follow` - Follow each repository\n\* `flash` - Flash everywhere\n\* `off` - Off everywhere')
        .optional()
        .describe(
            "Automatic reviews of the user's own pull requests in every repository this project reviews: 'follow' (default) uses each repository's rule, 'flash' gives automatic Flash everywhere, and 'off' turns automatic Flash off everywhere. A choice for one repository wins over this default.\n\n\* `follow` - Follow each repository\n\* `flash` - Flash everywhere\n\* `off` - Off everywhere"
        ),
    resolve_comments: zod
        .boolean()
        .optional()
        .describe(
            "After a Full review of the user's pull requests is published, run the resolution stage: triage the unresolved review threads, implement the worth-and-safe fixes on the PR branch, and reply on every thread. Off by default. Personal only: no project default applies."
        ),
    urgency_threshold: zod
        .enum(['consider', 'should_fix', 'must_fix'])
        .describe('\* `consider` - Consider (all)\n\* `should_fix` - Should fix\n\* `must_fix` - Must fix')
        .optional()
        .describe(
            "Minimum priority a validated Full review finding needs to be published: 'consider' publishes everything, 'should_fix' drops consider-level findings, 'must_fix' publishes only blocking issues. Without the user's own value the project default applies.\n\n\* `consider` - Consider (all)\n\* `should_fix` - Should fix\n\* `must_fix` - Must fix"
        ),
    celebrate_clean_reviews: zod
        .boolean()
        .optional()
        .describe(
            "Show a fun image in the review comment when a Full review of the user's pull requests finds nothing to raise. Without the user's own value the project default applies."
        ),
    review_inbox_prs: zod
        .boolean()
        .optional()
        .describe(
            'Review the pull requests the agent opens for Inbox reports assigned to the user: ReviewHog reviews each one and posts its findings to the pull request. Off by default.'
        ),
    stamphog_review_inbox_prs: zod
        .boolean()
        .optional()
        .describe(
            "Also have hosted Stamphog review those same Inbox pull requests: an approve-first review that posts a real GitHub approval when the change passes, and a comment when it doesn't. Only takes effect when the project has a synced, enabled Stamphog repository (see stamphog_connected)."
        ),
})

/**
 * Make a `review-hog-validation-*` skill the single validator that runs on the requesting user's PR reviews, switching the user's other validators off in the same call. Only skills visible to the user — the canonical plus the customs they authored — can be selected; anything else 404s. Upserts the per-user config row, so selecting a freshly authored custom validator works in one call.
 * @summary Select the active review validator
 */
export const ReviewHogValidatorsPartialUpdateBody = /* @__PURE__ */ zod.object({
    active: zod
        .boolean()
        .optional()
        .describe(
            "Set true to make this the single validator that runs on the user's PR reviews. Only true is accepted — validators are single-active, so you switch by selecting a different one, not by deactivating the current one."
        ),
})
