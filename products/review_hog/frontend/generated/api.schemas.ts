/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ReviewBlindSpotsConfigApi {
    /** Name of the `review-hog-blind-spots-*` skill this row represents (the sweep's identity). */
    skill_name: string
    /** Whether this blind-spots skill runs the sweep on the requesting user's PR reviews on this project. */
    active: boolean
    /** The blind-spots skill's description, for display in the config UI. */
    description: string
    /** The blind-spots skill's SKILL.md body, for the read-only skill viewer. */
    body: string
}

export interface PatchedReviewBlindSpotsConfigSelectApi {
    /** Set true to make this the single blind-spots skill that runs on the user's PR reviews. Only true is accepted — the blind-spot check is single-active, so you switch by selecting a different skill, not by deactivating the current one. */
    active?: boolean
}

/**
 * * `all` - All repositories
 * * `selected` - Only selected repositories
 */
export type ReviewInstallationClaimScopeEnumApi =
    (typeof ReviewInstallationClaimScopeEnumApi)[keyof typeof ReviewInstallationClaimScopeEnumApi]

export const ReviewInstallationClaimScopeEnumApi = {
    All: 'all',
    Selected: 'selected',
} as const

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Student: 'student',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface ReviewInstallationClaimApi {
    /** Id of the claim. */
    readonly id: string
    /** The GitHub App installation id. */
    readonly installation_id: string
    /** 'all' (every repository no other project selected, including future ones) or 'selected'.
     *
     * * `all` - All repositories
     * * `selected` - Only selected repositories */
    readonly scope: ReviewInstallationClaimScopeEnumApi
    /** The GitHub account (organization or user) of the installation. */
    readonly account_name: string
    /** Who made the claim. */
    readonly created_by: UserBasicApi | null
    /** When the claim was made. */
    readonly created_at: string
}

export interface ReviewInstallationClaimCreateApi {
    /**
     * The GitHub App installation id.
     * @maxLength 64
     */
    installation_id: string
    /** 'all' reviews every repository of the installation that no other project selected. At most one project per installation can choose it. 'selected' reviews only selected repositories.
     *
     * * `all` - All repositories
     * * `selected` - Only selected repositories */
    scope: ReviewInstallationClaimScopeEnumApi
}

export interface ReviewProjectRefApi {
    /**
     * Id of the other project. Null when it belongs to another organization.
     * @nullable
     */
    id: number | null
    /**
     * Name of the other project. Null when it belongs to another organization.
     * @nullable
     */
    name: string | null
}

export interface ReviewHogSettingsErrorApi {
    /** Why the request was rejected. */
    error: string
    /** The project that already holds the repository or the installation, if any. */
    conflicting_project: ReviewProjectRefApi | null
}

export interface PatchedReviewInstallationClaimUpdateApi {
    /** 'all' or 'selected'. Switching to 'selected' removes the exceptions of the repositories that leave the project.
     *
     * * `all` - All repositories
     * * `selected` - Only selected repositories */
    scope?: ReviewInstallationClaimScopeEnumApi
}

export interface ReviewPerspectiveConfigApi {
    /** Name of the `review-hog-perspective-*` skill this row toggles (the perspective's identity). */
    skill_name: string
    /** Whether this perspective runs on the acting user's PR reviews on this project. */
    enabled: boolean
    /** The perspective skill's description, for display in the config UI. */
    description: string
    /** The perspective skill's SKILL.md body, for the read-only skill viewer. */
    body: string
}

export interface PatchedReviewPerspectiveConfigUpdateApi {
    /** Set true to run this perspective on the user's PR reviews, false to stop running it. */
    enabled?: boolean
}

/**
 * * `everyone` - Automatic Flash for everyone
 * * `listed` - Automatic Flash for these people
 * * `off` - Automatic Flash opt-in only
 */
export type AutomaticFlashForEnumApi = (typeof AutomaticFlashForEnumApi)[keyof typeof AutomaticFlashForEnumApi]

export const AutomaticFlashForEnumApi = {
    Everyone: 'everyone',
    Listed: 'listed',
    Off: 'off',
} as const

/**
 * * `skip` - Not reviewed
 * * `run` - Automatic Flash
 */
export type ReviewProjectSettingsBotPullRequestsEnumApi =
    (typeof ReviewProjectSettingsBotPullRequestsEnumApi)[keyof typeof ReviewProjectSettingsBotPullRequestsEnumApi]

export const ReviewProjectSettingsBotPullRequestsEnumApi = {
    Skip: 'skip',
    Run: 'run',
} as const

/**
 * * `consider` - Consider (all)
 * * `should_fix` - Should fix
 * * `must_fix` - Must fix
 */
export type UrgencyThresholdEnumApi = (typeof UrgencyThresholdEnumApi)[keyof typeof UrgencyThresholdEnumApi]

export const UrgencyThresholdEnumApi = {
    Consider: 'consider',
    ShouldFix: 'should_fix',
    MustFix: 'must_fix',
} as const

/**
 * * `listed` - Listed
 * * `excepted` - Excepted
 */
export type ReviewRepositoryPersonKindEnumApi =
    (typeof ReviewRepositoryPersonKindEnumApi)[keyof typeof ReviewRepositoryPersonKindEnumApi]

export const ReviewRepositoryPersonKindEnumApi = {
    Listed: 'listed',
    Excepted: 'excepted',
} as const

export interface ReviewRepositoryPersonApi {
    /** Id of this list entry. Use it to remove the person. */
    readonly id: string
    /** The project member on the list. */
    readonly user: UserBasicApi
    /** Which list: 'listed' (gets automatic reviews when the rule reviews only listed people) or 'excepted' (skipped when the rule reviews everyone).
     *
     * * `listed` - Listed
     * * `excepted` - Excepted */
    readonly kind: ReviewRepositoryPersonKindEnumApi
}

export interface ReviewInstallationApi {
    /** The GitHub App installation id. */
    installation_id: string
    /** The GitHub account (organization or user) of the installation. */
    account_name: string
    /** Who connected the installation to this project. Automatic Standard reviews of bot pull requests run as this user. */
    connected_by: UserBasicApi | null
    /**
     * Id of this project's claim. Null when the project reviews nothing there.
     * @nullable
     */
    claim_id: string | null
    /** Which repositories this project reviews: 'all' (every repository no other project selected, including future ones), 'selected' (only the selected ones), or null (none).
     *
     * * `all` - All repositories
     * * `selected` - Only selected repositories */
    scope: ReviewInstallationClaimScopeEnumApi | null
    /** Another project that takes all repositories of the installation, if any. */
    all_taken_by_project: ReviewProjectRefApi | null
}

export interface ReviewProjectSettingsApi {
    /** Who gets automatic Standard reviews in the repositories this project reviews: 'everyone' (except the excepted people), 'listed' (only the listed people), or 'off' (only people who opt in, the default). A repository exception or a person's own choice wins over it.
     *
     * * `everyone` - Automatic Flash for everyone
     * * `listed` - Automatic Flash for these people
     * * `off` - Automatic Flash opt-in only */
    flash_for?: AutomaticFlashForEnumApi
    /** Pull requests from bots, and from authors who are not project members, in every repository this project reviews: 'skip' (not reviewed, the default) or 'run' (an automatic Standard review that runs as the person who connected GitHub, with default settings and no changes to the pull request).
     *
     * * `skip` - Not reviewed
     * * `run` - Automatic Flash */
    bot_prs?: ReviewProjectSettingsBotPullRequestsEnumApi
    /** Project default for the minimum priority a Deep review publishes: 'consider' (all, the built-in default), 'should_fix', or 'must_fix'. A person's own value wins.
     *
     * * `consider` - Consider (all)
     * * `should_fix` - Should fix
     * * `must_fix` - Must fix */
    urgency_threshold?: UrgencyThresholdEnumApi
    /** Project default for the image in a Deep review that finds nothing to raise. On by default. A person's own value wins. */
    celebrate_clean_reviews?: boolean
    /** The people on the project rule's two lists. Only the list that matches flash_for has an effect. */
    readonly people: readonly ReviewRepositoryPersonApi[]
    /** Every GitHub installation connected to this project, and which of its repositories this project reviews. */
    readonly installations: readonly ReviewInstallationApi[]
    /** Whether the requesting user is a project admin and can change these settings. */
    readonly can_edit: boolean
}

export interface PatchedReviewProjectSettingsApi {
    /** Who gets automatic Standard reviews in the repositories this project reviews: 'everyone' (except the excepted people), 'listed' (only the listed people), or 'off' (only people who opt in, the default). A repository exception or a person's own choice wins over it.
     *
     * * `everyone` - Automatic Flash for everyone
     * * `listed` - Automatic Flash for these people
     * * `off` - Automatic Flash opt-in only */
    flash_for?: AutomaticFlashForEnumApi
    /** Pull requests from bots, and from authors who are not project members, in every repository this project reviews: 'skip' (not reviewed, the default) or 'run' (an automatic Standard review that runs as the person who connected GitHub, with default settings and no changes to the pull request).
     *
     * * `skip` - Not reviewed
     * * `run` - Automatic Flash */
    bot_prs?: ReviewProjectSettingsBotPullRequestsEnumApi
    /** Project default for the minimum priority a Deep review publishes: 'consider' (all, the built-in default), 'should_fix', or 'must_fix'. A person's own value wins.
     *
     * * `consider` - Consider (all)
     * * `should_fix` - Should fix
     * * `must_fix` - Must fix */
    urgency_threshold?: UrgencyThresholdEnumApi
    /** Project default for the image in a Deep review that finds nothing to raise. On by default. A person's own value wins. */
    celebrate_clean_reviews?: boolean
    /** The people on the project rule's two lists. Only the list that matches flash_for has an effect. */
    readonly people?: readonly ReviewRepositoryPersonApi[]
    /** Every GitHub installation connected to this project, and which of its repositories this project reviews. */
    readonly installations?: readonly ReviewInstallationApi[]
    /** Whether the requesting user is a project admin and can change these settings. */
    readonly can_edit?: boolean
}

export interface ReviewRepositoryPersonRequestApi {
    /** Id of the project member to add. Must be an active member. */
    user_id: number
    /** Which list to add the person to: 'listed' or 'excepted'.
     *
     * * `listed` - Listed
     * * `excepted` - Excepted */
    kind: ReviewRepositoryPersonKindEnumApi
}

export interface ReviewRepositoryApi {
    /** Id of the repository entry. */
    readonly id: string
    /** The GitHub App installation that sees it. */
    readonly installation_id: string
    /**
     * GitHub's id of the repository. Null until it is first seen.
     * @nullable
     */
    readonly github_repo_id: number | null
    /** GitHub repository in 'owner/name' form. */
    readonly full_name: string
    /** Whether this project selected the repository. A selected repository belongs to this project even when another project takes all repositories of the installation. */
    readonly selected: boolean
    /** The repository exception: 'everyone', 'listed', or 'off' (opt-in only). Null when the repository follows the project rule.
     *
     * * `everyone` - Automatic Flash for everyone
     * * `listed` - Automatic Flash for these people
     * * `off` - Automatic Flash opt-in only */
    readonly flash_for: AutomaticFlashForEnumApi | null
    /** The people on the exception's two lists. Only the list that matches flash_for has an effect. */
    readonly people: readonly ReviewRepositoryPersonApi[]
    /** Who added the repository. */
    readonly created_by: UserBasicApi | null
    /** When the repository was added. */
    readonly created_at: string
}

export interface ReviewRepositoryWriteApi {
    /**
     * The GitHub App installation that sees the repository, from the overview.
     * @maxLength 64
     */
    installation_id: string
    /**
     * GitHub repository in 'owner/name' form, spelled as GitHub returns it.
     * @maxLength 200
     */
    full_name: string
    /**
     * GitHub's id of the repository, from the overview. Keeps renames.
     * @minimum 1
     */
    github_repo_id?: number
    /** True includes the repository into this project, also when another project takes all repositories of the installation. False removes it; with an 'only selected' claim its exception goes too. */
    selected?: boolean
    /** The repository exception: 'everyone', 'listed', or 'off'. Null clears it, so the repository follows the project rule again. Omit it to keep the current value.
     *
     * * `everyone` - Automatic Flash for everyone
     * * `listed` - Automatic Flash for these people
     * * `off` - Automatic Flash opt-in only */
    flash_for?: AutomaticFlashForEnumApi | null
}

export interface ReviewRepositoryWriteResponseApi {
    /** The repository entry after the write. Null when nothing is left to store, so the entry was deleted and the repository follows the project rule or left the project. */
    repository: ReviewRepositoryApi | null
    /** The project that took all repositories of the installation, when this write took the repository from it. */
    taken_from_project: ReviewProjectRefApi | null
}

/**
 * * `flash` - Flash
 * * `off` - Off
 */
export type ReviewUserRepositoryChoiceModeEnumApi =
    (typeof ReviewUserRepositoryChoiceModeEnumApi)[keyof typeof ReviewUserRepositoryChoiceModeEnumApi]

export const ReviewUserRepositoryChoiceModeEnumApi = {
    Flash: 'flash',
    Off: 'off',
} as const

export interface ReviewRepositoryChoiceApi {
    /** Id of the choice. Use it to clear the choice. */
    readonly id: string
    /** The GitHub App installation. */
    readonly installation_id: string
    /**
     * GitHub's repository id.
     * @nullable
     */
    readonly github_repo_id: number | null
    /** GitHub repository in 'owner/name' form. */
    readonly full_name: string
    /** 'flash' or 'off' for the user's own pull requests in this repository.
     *
     * * `flash` - Flash
     * * `off` - Off */
    readonly mode: ReviewUserRepositoryChoiceModeEnumApi
}

export interface ReviewRepositoryChoiceWriteApi {
    /**
     * The GitHub App installation.
     * @maxLength 64
     */
    installation_id: string
    /**
     * GitHub repository in 'owner/name' form.
     * @maxLength 200
     */
    full_name: string
    /**
     * GitHub's repository id.
     * @minimum 1
     */
    github_repo_id?: number
    /** The requesting user's own automatic review for their pull requests in this repository: 'flash' or 'off'. A value equal to what the user inherits clears the choice instead.
     *
     * * `flash` - Flash
     * * `off` - Off */
    mode: ReviewUserRepositoryChoiceModeEnumApi
}

/**
 * * `own_repository_choice` - Own choice for this repository
 * * `own_default` - Own default
 * * `repository_everyone` - The repository exception reviews everyone
 * * `repository_excepted` - Excepted by the repository exception
 * * `repository_listed` - Listed by the repository exception
 * * `repository_not_listed` - Not listed by the repository exception
 * * `repository_opt_in` - The repository exception reviews only people who opt in
 * * `project_everyone` - The project reviews everyone
 * * `project_excepted` - Excepted by the project
 * * `project_listed` - Listed by the project
 * * `project_not_listed` - Not listed by the project
 * * `project_opt_in` - The project reviews only people who opt in
 * * `bot_reviewed` - The project reviews bot pull requests
 * * `bot_skipped` - The project does not review bot pull requests
 * * `not_in_project` - This project does not review the repository
 */
export type AutomaticReviewReasonEnumApi =
    (typeof AutomaticReviewReasonEnumApi)[keyof typeof AutomaticReviewReasonEnumApi]

export const AutomaticReviewReasonEnumApi = {
    OwnRepositoryChoice: 'own_repository_choice',
    OwnDefault: 'own_default',
    RepositoryEveryone: 'repository_everyone',
    RepositoryExcepted: 'repository_excepted',
    RepositoryListed: 'repository_listed',
    RepositoryNotListed: 'repository_not_listed',
    RepositoryOptIn: 'repository_opt_in',
    ProjectEveryone: 'project_everyone',
    ProjectExcepted: 'project_excepted',
    ProjectListed: 'project_listed',
    ProjectNotListed: 'project_not_listed',
    ProjectOptIn: 'project_opt_in',
    BotReviewed: 'bot_reviewed',
    BotSkipped: 'bot_skipped',
    NotInProject: 'not_in_project',
} as const

export interface AutomaticReviewDecisionApi {
    /** Whether the requesting user's own pull requests get automatic Standard reviews in this repository. */
    flash: boolean
    /** Which rule decided: the user's own choice ('own_repository_choice', 'own_default'), the repository exception ('repository_*'), the project rule ('project_*'), or 'not_in_project' when this project does not review the repository.
     *
     * * `own_repository_choice` - Own choice for this repository
     * * `own_default` - Own default
     * * `repository_everyone` - The repository exception reviews everyone
     * * `repository_excepted` - Excepted by the repository exception
     * * `repository_listed` - Listed by the repository exception
     * * `repository_not_listed` - Not listed by the repository exception
     * * `repository_opt_in` - The repository exception reviews only people who opt in
     * * `project_everyone` - The project reviews everyone
     * * `project_excepted` - Excepted by the project
     * * `project_listed` - Listed by the project
     * * `project_not_listed` - Not listed by the project
     * * `project_opt_in` - The project reviews only people who opt in
     * * `bot_reviewed` - The project reviews bot pull requests
     * * `bot_skipped` - The project does not review bot pull requests
     * * `not_in_project` - This project does not review the repository */
    reason: AutomaticReviewReasonEnumApi
}

export interface ReviewRepositoryChoiceWriteResponseApi {
    /** The stored choice. Null when the value equals the inherited one. */
    choice: ReviewRepositoryChoiceApi | null
    /** What the requesting user's own pull requests get in this repository after the write. */
    my_result: AutomaticReviewDecisionApi
}

/**
 * * `this_project` - This project
 * * `other_project` - Another project
 * * `none` - No project
 */
export type RepositoryOwnerKindEnumApi = (typeof RepositoryOwnerKindEnumApi)[keyof typeof RepositoryOwnerKindEnumApi]

export const RepositoryOwnerKindEnumApi = {
    ThisProject: 'this_project',
    OtherProject: 'other_project',
    None: 'none',
} as const

export interface ReviewRepositoryExceptionApi {
    /** The exception's rule: 'everyone', 'listed', or 'off'.
     *
     * * `everyone` - Automatic Flash for everyone
     * * `listed` - Automatic Flash for these people
     * * `off` - Automatic Flash opt-in only */
    flash_for: AutomaticFlashForEnumApi
    /** The people on the exception's two lists. */
    people: ReviewRepositoryPersonApi[]
}

export interface ReviewRepositoryOverviewEntryApi {
    /** GitHub repository in 'owner/name' form. */
    full_name: string
    /**
     * GitHub's repository id.
     * @nullable
     */
    github_repo_id: number | null
    /** Which project reviews the repository: 'this_project', 'other_project', or 'none'.
     *
     * * `this_project` - This project
     * * `other_project` - Another project
     * * `none` - No project */
    owner: RepositoryOwnerKindEnumApi
    /** The other project that reviews the repository, when owner is 'other_project'. */
    owner_project: ReviewProjectRefApi | null
    /** Whether this project reviews the repository. */
    in_project: boolean
    /** Whether this project selected the repository explicitly. */
    selected: boolean
    /**
     * Id of this project's repository entry, for the people list endpoints.
     * @nullable
     */
    repository_id: string | null
    /** This project's repository exception. Null when the repository follows the project. */
    exception: ReviewRepositoryExceptionApi | null
    /** The requesting user's own choice for this repository: 'flash', 'off', or null.
     *
     * * `flash` - Flash
     * * `off` - Off */
    my_choice: ReviewUserRepositoryChoiceModeEnumApi | null
    /**
     * Id of that choice, to clear it.
     * @nullable
     */
    my_choice_id: string | null
    /** What the requesting user's own pull requests get here, and the rule that decided it. */
    my_result: AutomaticReviewDecisionApi
    /** What the requesting user's own pull requests would get here without their choice for this repository. Equals my_result when there is no choice. */
    inherited_result: AutomaticReviewDecisionApi
    /** What the requesting user's own pull requests would get here from the repository exception or the project rule alone, without their default and their choice for this repository. */
    repository_result: AutomaticReviewDecisionApi
}

export interface ReviewRepositoryOverviewApi {
    /** The listed GitHub App installation. */
    installation_id: string
    /** This project's claim on the installation: 'all', 'selected', or null.
     *
     * * `all` - All repositories
     * * `selected` - Only selected repositories */
    claim_scope: ReviewInstallationClaimScopeEnumApi | null
    /** One page of repositories. */
    results: ReviewRepositoryOverviewEntryApi[]
    /** Repositories that match the search and the view. */
    total: number
    /** Whether more entries follow this page. */
    has_more: boolean
    /**
     * Offset of the next page, or null.
     * @nullable
     */
    next_offset: number | null
    /** How many of the requesting user's own repository choices in this project give something other than their default. Counts every installation, so the search, the view, and the page do not change it. */
    my_choices_unlike_default: number
}

export interface ReviewResolutionConfigApi {
    /** Name of the `review-hog-resolution-*` skill this row represents (the criteria's identity). */
    skill_name: string
    /** Whether these criteria drive the resolution stage on the requesting user's PRs on this project. */
    active: boolean
    /** The resolution skill's description, for display in the config UI. */
    description: string
    /** The resolution skill's SKILL.md body, for the read-only skill viewer. */
    body: string
}

export interface PatchedReviewResolutionConfigSelectApi {
    /** Set true to make these the single resolution criteria applied on the user's PRs. Only true is accepted — resolution criteria are single-active, so you switch by selecting a different skill, not by deactivating the current one. */
    active?: boolean
}

/**
 * * `full` - Deep
 * * `flash` - Standard
 */
export type ReviewTriggerReviewModeEnumApi =
    (typeof ReviewTriggerReviewModeEnumApi)[keyof typeof ReviewTriggerReviewModeEnumApi]

export const ReviewTriggerReviewModeEnumApi = {
    Full: 'full',
    Flash: 'flash',
} as const

/**
 * * `pipeline` - Pipeline
 * * `single_agent` - Single agent
 */
export type ReviewTurnDesignEnumApi = (typeof ReviewTurnDesignEnumApi)[keyof typeof ReviewTurnDesignEnumApi]

export const ReviewTurnDesignEnumApi = {
    Pipeline: 'pipeline',
    SingleAgent: 'single_agent',
} as const

/**
 * * `fetching` - fetching
 * * `chunking` - chunking
 * * `selecting` - selecting
 * * `reviewing` - reviewing
 * * `deduplicating` - deduplicating
 * * `validating` - validating
 * * `finalizing` - finalizing
 * * `single_agent_preparing` - single_agent_preparing
 * * `single_agent_reviewing` - single_agent_reviewing
 * * `single_agent_finalizing` - single_agent_finalizing
 */
export type ReviewStageEnumApi = (typeof ReviewStageEnumApi)[keyof typeof ReviewStageEnumApi]

export const ReviewStageEnumApi = {
    Fetching: 'fetching',
    Chunking: 'chunking',
    Selecting: 'selecting',
    Reviewing: 'reviewing',
    Deduplicating: 'deduplicating',
    Validating: 'validating',
    Finalizing: 'finalizing',
    SingleAgentPreparing: 'single_agent_preparing',
    SingleAgentReviewing: 'single_agent_reviewing',
    SingleAgentFinalizing: 'single_agent_finalizing',
} as const

export interface ReviewProgressApi {
    /** How far the in-flight review turn has come: fetching the diff, chunking, picking each chunk's perspectives, reviewing chunks, merging overlapping findings, validating them, or finalizing (building and publishing the review). A single-agent Standard turn reports its own `single_agent_*` stages instead: preparing, reviewing (main and lens sessions), and finalizing (merging, capping, and publishing the findings).
     *
     * * `fetching` - fetching
     * * `chunking` - chunking
     * * `selecting` - selecting
     * * `reviewing` - reviewing
     * * `deduplicating` - deduplicating
     * * `validating` - validating
     * * `finalizing` - finalizing
     * * `single_agent_preparing` - single_agent_preparing
     * * `single_agent_reviewing` - single_agent_reviewing
     * * `single_agent_finalizing` - single_agent_finalizing */
    review_stage: ReviewStageEnumApi
    /**
     * Work units finished within the stage; null when the stage has no counter.
     * @nullable
     */
    done: number | null
    /**
     * Work units the stage expects in total; null when unknown.
     * @nullable
     */
    total: number | null
}

/**
 * * `resolving` - resolving
 * * `stopped` - stopped
 */
export type ResolutionStatusEnumApi = (typeof ResolutionStatusEnumApi)[keyof typeof ResolutionStatusEnumApi]

export const ResolutionStatusEnumApi = {
    Resolving: 'resolving',
    Stopped: 'stopped',
} as const

export interface ReviewResolutionStatusApi {
    /** Where the run stands: `resolving` while threads are being settled, `stopped` when the run died partway (went quiet with no closing summary).
     *
     * * `resolving` - resolving
     * * `stopped` - stopped */
    resolution_status: ResolutionStatusEnumApi
    /** Queued threads settled so far this run. */
    done: number
    /** Threads queued for this run. */
    total: number
    /** Settled threads that were fixed with a commit to the branch. */
    fixed: number
    /** Settled threads left for the author: judged worth doing but not safe to fix unattended. */
    needs_attention: number
}

/**
 * * `resolving` - Resolving
 * * `stopped` - Stopped
 * * `completed` - Completed
 */
export type ReviewLatestResolutionStatusEnumApi =
    (typeof ReviewLatestResolutionStatusEnumApi)[keyof typeof ReviewLatestResolutionStatusEnumApi]

export const ReviewLatestResolutionStatusEnumApi = {
    Resolving: 'resolving',
    Stopped: 'stopped',
    Completed: 'completed',
} as const

export interface ReviewLatestResolutionApi {
    /** Where the run stands: 'resolving' while threads are being settled, 'completed' when it finished, 'stopped' when it died partway or a newer review turn replaced it.
     *
     * * `resolving` - Resolving
     * * `stopped` - Stopped
     * * `completed` - Completed */
    status: ReviewLatestResolutionStatusEnumApi
    /** When the run queued its threads. */
    started_at: string
    /**
     * When the run finished; null unless the status is 'completed'.
     * @nullable
     */
    completed_at: string | null
    /** Threads queued for this run. */
    total: number
    /** Threads the run fixed with a commit to the branch. */
    fixed: number
    /** Threads left for the author: judged worth doing but not safe to fix unattended. */
    needs_attention: number
    /** SHAs of the run's fix commits, oldest first. Only commits confirmed on the pull request branch that touch no protected files; the replies on GitHub link the same commits. */
    commits: string[]
}

export interface ReviewRecentReviewApi {
    /** The review report's id, for fetching the review's detail. */
    id: string
    /** The reviewed repository, as `owner/repo`. */
    repository: string
    /**
     * The reviewed pull request's number; null for a branch target with no PR yet.
     * @nullable
     */
    pr_number: number | null
    /**
     * The pull request's title, from the latest reviewed snapshot; null if unknown.
     * @nullable
     */
    pr_title: string | null
    /**
     * The pull request author's GitHub login; null if unknown.
     * @nullable
     */
    pr_author: string | null
    /**
     * Lines added by the PR; null if unknown.
     * @nullable
     */
    additions: number | null
    /**
     * Lines deleted by the PR; null if unknown.
     * @nullable
     */
    deletions: number | null
    /**
     * Files the PR changes; null if unknown.
     * @nullable
     */
    changed_files: number | null
    /** The pull request's head branch. */
    head_branch: string
    /** Where to see the review on GitHub: the pull request when its URL is known, otherwise the head branch. */
    github_url: string
    /** How many review turns have completed on this report. */
    run_count: number
    /**
     * When the latest review turn completed; null while the first is in flight.
     * @nullable
     */
    last_run_at: string | null
    /** Whether any turn of this report has been published back to GitHub. See `turn_published` for the returned turn. */
    published: boolean
    /** Whether the returned turn (the latest completed one, or `run_index` on the detail) was published to GitHub. False when it found nothing to post or publishing was off. */
    turn_published: boolean
    /** What the returned turn ran: 'full' (Deep) or 'flash' (Standard). Null when the turn did not record its mode (turns from before the mode was recorded).
     *
     * * `full` - Deep
     * * `flash` - Standard */
    review_mode: ReviewTriggerReviewModeEnumApi | null
    /** How the returned turn found its issues. 'pipeline': chunks, perspectives, a blind-spot sweep and a separate validation step. 'single_agent': one main review plus focused lenses, with no separate validation step. Null when the turn recorded no design (turns from before it was recorded ran the pipeline).
     *
     * * `pipeline` - Pipeline
     * * `single_agent` - Single agent */
    review_design: ReviewTurnDesignEnumApi | null
    /**
     * Link to the review's status comment on the pull request; null when there is no status comment or no pull request URL.
     * @nullable
     */
    status_comment_url: string | null
    /** Whether a Deep review of this pull request has been published. No Standard review runs after one. */
    full_review_published: boolean
    /** Whether a run is on this report right now: a review turn or a resolution run (activity within the last 30 minutes). */
    in_progress: boolean
    /** The in-flight review turn's stage and counters; null unless a review turn is running (a resolving report carries `resolution` instead). */
    progress: ReviewProgressApi | null
    /** The report's latest resolution run (settling the PR's review threads): live progress while it runs, or where it stopped when it died partway. Null when there is none, it completed, or a newer review turn superseded it. */
    resolution: ReviewResolutionStatusApi | null
    /** The report's latest resolution run, completed runs included: its status, counts, and fix commits. Null when no resolution run has queued threads on this report. */
    latest_resolution: ReviewLatestResolutionApi | null
    /** The latest turn's valid findings at must_fix effective priority. */
    must_fix_count: number
    /** The latest turn's valid findings at should_fix effective priority. */
    should_fix_count: number
    /** The latest turn's valid findings at consider effective priority. */
    consider_count: number
    /** All findings the latest turn raised after dedupe, before validation. */
    candidate_count: number
    /** The latest turn's findings the validator dismissed as not worth publishing. */
    dismissed_count: number
    /**
     * Meaningful files the latest turn actually read, after skipping generated/lock/snapshot files; null if unknown.
     * @nullable
     */
    files_reviewed: number | null
    /**
     * Reviewable chunks the latest turn split the PR into; null if unknown.
     * @nullable
     */
    chunk_count: number | null
    /**
     * Review perspectives that read each chunk in the latest turn; null if unknown.
     * @nullable
     */
    perspective_count: number | null
    /**
     * Raw issues the perspectives raised in the latest turn, before dedupe; null if unknown.
     * @nullable
     */
    perspective_issue_count: number | null
    /**
     * Raw issues the blind-spot sweep added in the latest turn, before dedupe; null if unknown.
     * @nullable
     */
    blind_spot_issue_count: number | null
}

export interface ReviewRecentReviewsPageApi {
    /** The scoped reviews: in-progress runs first, then completed newest first. */
    results: ReviewRecentReviewApi[]
    /** Whether reviews exist beyond this page — drives the list's "Show more" button. */
    has_more: boolean
}

export interface ReviewSelectionChunkApi {
    /** The chunk this row describes, as numbered by the chunker. */
    chunk_id: number
    /**
     * The chunker's category for the chunk; null on the deterministic single-chunk path.
     * @nullable
     */
    chunk_type: string | null
    /** The chunk's files, from the turn's chunk set. */
    files: string[]
    /** Perspectives the selector ran on this chunk, in pass order. */
    perspectives: string[]
    /** Roster perspectives the selector skipped on this chunk, in pass order. */
    skipped: string[]
    /** The selector's one-line reasoning for this chunk's picks. */
    reason: string
}

export interface ReviewPerspectiveSelectionApi {
    /** Every enabled perspective the selector chose from, in pass order. */
    roster: string[]
    /** Per-chunk picks with reasons, in chunk order. */
    chunks: ReviewSelectionChunkApi[]
}

export interface ReviewFindingLineRangeApi {
    /** First affected line. */
    start: number
    /**
     * Last affected line; null for a single line.
     * @nullable
     */
    end: number | null
}

/**
 * * `must_fix` - must_fix
 * * `should_fix` - should_fix
 * * `consider` - consider
 */
export type ReviewIssuePriorityEnumApi = (typeof ReviewIssuePriorityEnumApi)[keyof typeof ReviewIssuePriorityEnumApi]

export const ReviewIssuePriorityEnumApi = {
    MustFix: 'must_fix',
    ShouldFix: 'should_fix',
    Consider: 'consider',
} as const

/**
 * * `bug` - bug
 * * `security` - security
 * * `performance` - performance
 * * `code_quality` - code_quality
 * * `best_practice` - best_practice
 * * `documentation` - documentation
 * * `testing` - testing
 * * `accessibility` - accessibility
 * * `compatibility` - compatibility
 */
export type ValidatorCategoryEnumApi = (typeof ValidatorCategoryEnumApi)[keyof typeof ValidatorCategoryEnumApi]

export const ValidatorCategoryEnumApi = {
    Bug: 'bug',
    Security: 'security',
    Performance: 'performance',
    CodeQuality: 'code_quality',
    BestPractice: 'best_practice',
    Documentation: 'documentation',
    Testing: 'testing',
    Accessibility: 'accessibility',
    Compatibility: 'compatibility',
} as const

export interface ReviewFindingApi {
    /** One-line summary of the finding. */
    title: string
    /** Repository-relative path of the affected file. */
    file: string
    /** Affected line ranges within the file. */
    lines: ReviewFindingLineRangeApi[]
    /** Description of the problem. */
    body: string
    /** The specific fix or improvement the reviewer proposes. */
    suggestion: string
    /** The priority that gates publishing: the validator's override when set, else the reviewer's.
     *
     * * `must_fix` - must_fix
     * * `should_fix` - should_fix
     * * `consider` - consider */
    effective_priority: ReviewIssuePriorityEnumApi
    /** The reviewer's original priority, before any validator override.
     *
     * * `must_fix` - must_fix
     * * `should_fix` - should_fix
     * * `consider` - consider */
    reviewer_priority: ReviewIssuePriorityEnumApi
    /**
     * The review skill that produced the finding (perspective or blind-spot sweep).
     * @nullable
     */
    source_perspective: string | null
    /** The validator's category for the finding; null when it didn't set one.
     *
     * * `bug` - bug
     * * `security` - security
     * * `performance` - performance
     * * `code_quality` - code_quality
     * * `best_practice` - best_practice
     * * `documentation` - documentation
     * * `testing` - testing
     * * `accessibility` - accessibility
     * * `compatibility` - compatibility */
    validator_category: ValidatorCategoryEnumApi | null
    /** The validator's argumentation for keeping or dismissing the finding. */
    validator_note: string
}

/**
 * * `must_fix` - Must fix
 * * `should_fix` - Should fix
 * * `consider` - Consider
 */
export type ReviewDroppedFindingPriorityEnumApi =
    (typeof ReviewDroppedFindingPriorityEnumApi)[keyof typeof ReviewDroppedFindingPriorityEnumApi]

export const ReviewDroppedFindingPriorityEnumApi = {
    MustFix: 'must_fix',
    ShouldFix: 'should_fix',
    Consider: 'consider',
} as const

/**
 * * `old_code` - On unchanged code
 * * `dedup_prior` - Repeat of an earlier review
 * * `dedup_comment` - Already in a PR comment
 * * `dedup_anchor` - Same spot as another finding
 * * `dedup_sibling` - Repeat of a finding
 * * `cap` - Over the limit
 */
export type ReviewDropDispositionEnumApi =
    (typeof ReviewDropDispositionEnumApi)[keyof typeof ReviewDropDispositionEnumApi]

export const ReviewDropDispositionEnumApi = {
    OldCode: 'old_code',
    DedupPrior: 'dedup_prior',
    DedupComment: 'dedup_comment',
    DedupAnchor: 'dedup_anchor',
    DedupSibling: 'dedup_sibling',
    Cap: 'cap',
} as const

export interface ReviewDroppedFindingApi {
    /** One-line summary of the finding. */
    title: string
    /** Repository-relative path of the affected file. */
    file: string
    /** Affected line ranges within the file. */
    lines: ReviewFindingLineRangeApi[]
    /** Description of the problem. */
    body: string
    /** The specific fix the reviewer proposes. Usually empty: a single-agent finding ends its body with the fix direction instead. */
    suggestion: string
    /** The reviewer's priority for the finding.
     *
     * * `must_fix` - Must fix
     * * `should_fix` - Should fix
     * * `consider` - Consider */
    priority: ReviewDroppedFindingPriorityEnumApi
    /**
     * The session that raised the finding: the main review or a lens.
     * @nullable
     */
    source_perspective: string | null
    /** Why the turn did not post the finding. `old_code`: a follow-up turn's minor finding on code that did not change since the last reviewed head. `dedup_prior`: repeats an earlier turn's finding. `dedup_comment`: repeats a PR comment. `dedup_anchor`: repeats a main-review finding at the same spot. `dedup_sibling`: repeats another finding from the same session or lens. `cap`: ranked below the per-review finding limit.
     *
     * * `old_code` - On unchanged code
     * * `dedup_prior` - Repeat of an earlier review
     * * `dedup_comment` - Already in a PR comment
     * * `dedup_anchor` - Same spot as another finding
     * * `dedup_sibling` - Repeat of a finding
     * * `cap` - Over the limit */
    disposition: ReviewDropDispositionEnumApi
    /**
     * For a dedup drop, what it repeats: an issue key, or `comment:<id>` for a PR comment. Null for other dispositions.
     * @nullable
     */
    duplicate_of: string | null
    /**
     * Link to the PR comment the finding repeats, when `duplicate_of` names one and the PR URL is known. Null otherwise.
     * @nullable
     */
    comment_url: string | null
    /**
     * For a `cap` drop, the finding's 1-based position in the turn's ranked findings. Null otherwise.
     * @nullable
     */
    rank: number | null
}

export interface ReviewDetailApi {
    /** The review report's id, for fetching the review's detail. */
    id: string
    /** The reviewed repository, as `owner/repo`. */
    repository: string
    /**
     * The reviewed pull request's number; null for a branch target with no PR yet.
     * @nullable
     */
    pr_number: number | null
    /**
     * The pull request's title, from the latest reviewed snapshot; null if unknown.
     * @nullable
     */
    pr_title: string | null
    /**
     * The pull request author's GitHub login; null if unknown.
     * @nullable
     */
    pr_author: string | null
    /**
     * Lines added by the PR; null if unknown.
     * @nullable
     */
    additions: number | null
    /**
     * Lines deleted by the PR; null if unknown.
     * @nullable
     */
    deletions: number | null
    /**
     * Files the PR changes; null if unknown.
     * @nullable
     */
    changed_files: number | null
    /** The pull request's head branch. */
    head_branch: string
    /** Where to see the review on GitHub: the pull request when its URL is known, otherwise the head branch. */
    github_url: string
    /** How many review turns have completed on this report. */
    run_count: number
    /**
     * When the latest review turn completed; null while the first is in flight.
     * @nullable
     */
    last_run_at: string | null
    /** Whether any turn of this report has been published back to GitHub. See `turn_published` for the returned turn. */
    published: boolean
    /** Whether the returned turn (the latest completed one, or `run_index` on the detail) was published to GitHub. False when it found nothing to post or publishing was off. */
    turn_published: boolean
    /** What the returned turn ran: 'full' (Deep) or 'flash' (Standard). Null when the turn did not record its mode (turns from before the mode was recorded).
     *
     * * `full` - Deep
     * * `flash` - Standard */
    review_mode: ReviewTriggerReviewModeEnumApi | null
    /** How the returned turn found its issues. 'pipeline': chunks, perspectives, a blind-spot sweep and a separate validation step. 'single_agent': one main review plus focused lenses, with no separate validation step. Null when the turn recorded no design (turns from before it was recorded ran the pipeline).
     *
     * * `pipeline` - Pipeline
     * * `single_agent` - Single agent */
    review_design: ReviewTurnDesignEnumApi | null
    /**
     * Link to the review's status comment on the pull request; null when there is no status comment or no pull request URL.
     * @nullable
     */
    status_comment_url: string | null
    /** Whether a Deep review of this pull request has been published. No Standard review runs after one. */
    full_review_published: boolean
    /** Whether a run is on this report right now: a review turn or a resolution run (activity within the last 30 minutes). */
    in_progress: boolean
    /** The in-flight review turn's stage and counters; null unless a review turn is running (a resolving report carries `resolution` instead). */
    progress: ReviewProgressApi | null
    /** The report's latest resolution run (settling the PR's review threads): live progress while it runs, or where it stopped when it died partway. Null when there is none, it completed, or a newer review turn superseded it. */
    resolution: ReviewResolutionStatusApi | null
    /** The report's latest resolution run, completed runs included: its status, counts, and fix commits. Null when no resolution run has queued threads on this report. */
    latest_resolution: ReviewLatestResolutionApi | null
    /** The latest turn's valid findings at must_fix effective priority. */
    must_fix_count: number
    /** The latest turn's valid findings at should_fix effective priority. */
    should_fix_count: number
    /** The latest turn's valid findings at consider effective priority. */
    consider_count: number
    /** All findings the latest turn raised after dedupe, before validation. */
    candidate_count: number
    /** The latest turn's findings the validator dismissed as not worth publishing. */
    dismissed_count: number
    /**
     * Meaningful files the latest turn actually read, after skipping generated/lock/snapshot files; null if unknown.
     * @nullable
     */
    files_reviewed: number | null
    /**
     * Reviewable chunks the latest turn split the PR into; null if unknown.
     * @nullable
     */
    chunk_count: number | null
    /**
     * Review perspectives that read each chunk in the latest turn; null if unknown.
     * @nullable
     */
    perspective_count: number | null
    /**
     * Raw issues the perspectives raised in the latest turn, before dedupe; null if unknown.
     * @nullable
     */
    perspective_issue_count: number | null
    /**
     * Raw issues the blind-spot sweep added in the latest turn, before dedupe; null if unknown.
     * @nullable
     */
    blind_spot_issue_count: number | null
    /** The review turn this detail describes, from 1 to `run_count`. */
    run_index: number
    /**
     * The PR head commit the returned turn reviewed. Anchors GitHub links to the exact code. Null for an older turn whose head was not recorded.
     * @nullable
     */
    head_sha: string | null
    /** The selector's per-chunk perspective plan for the latest turn; null when the turn ran without a selection (selector unavailable, failed, or the run predates it). */
    perspective_selection: ReviewPerspectiveSelectionApi | null
    /**
     * The rendered review body published to GitHub, as markdown. Only kept for the latest turn, so null when `run_index` selects an older turn.
     * @nullable
     */
    report_markdown: string | null
    /** The urgency threshold the returned turn's publishing gated on (stamped at finalize from the run's own resolve snapshot); null for turns that predate its recording — readers fall back to the viewer's current setting as an approximation.
     *
     * * `consider` - Consider (all)
     * * `should_fix` - Should fix
     * * `must_fix` - Must fix */
    run_urgency_threshold: UrgencyThresholdEnumApi | null
    /** The returned turn's validated findings, most urgent first. */
    findings: ReviewFindingApi[]
    /** The returned turn's findings the validator dismissed, with its reasoning. */
    dismissed_findings: ReviewFindingApi[]
    /** The returned turn's findings a single-agent (Standard) review raised but did not post, each with the reason. Empty for pipeline turns and for turns that predate the record. */
    dropped_findings: ReviewDroppedFindingApi[]
}

export interface ReviewPerspectiveStatItemApi {
    /** The review skill (perspective or blind-spot sweep) that raised the findings. */
    skill_name: string
    /** Findings this skill raised across the aggregated reviews (post-dedupe candidates). */
    raised: number
    /** Of those, findings the validator kept. */
    kept: number
    /** Of those, findings the validator dismissed. */
    dismissed: number
}

export interface ReviewPerspectiveStatsApi {
    /** How many recent completed reviews the stats aggregate over. */
    report_count: number
    /** Per-skill effectiveness across those reviews, most kept findings first. */
    perspectives: ReviewPerspectiveStatItemApi[]
}

/**
 * * `not_reviewed` - Not reviewed
 * * `queued` - Queued
 * * `reviewing` - Reviewing
 * * `resolving` - Resolving
 * * `idle` - Idle
 * * `unknown` - Unknown
 */
export type ReviewPRStateEnumApi = (typeof ReviewPRStateEnumApi)[keyof typeof ReviewPRStateEnumApi]

export const ReviewPRStateEnumApi = {
    NotReviewed: 'not_reviewed',
    Queued: 'queued',
    Reviewing: 'reviewing',
    Resolving: 'resolving',
    Idle: 'idle',
    Unknown: 'unknown',
} as const

export interface ReviewPRStatusLatestReviewApi {
    /** The review's id, for `review-hog-reviews-get`. */
    id: string
    /** What the turn ran: 'full' (Deep) or 'flash' (Standard). Null when the turn did not record it.
     *
     * * `full` - Deep
     * * `flash` - Standard */
    review_mode: ReviewTriggerReviewModeEnumApi | null
    /**
     * The PR head commit the turn reviewed.
     * @nullable
     */
    head_sha: string | null
    /** The turn's index, for `review-hog-reviews-get`. */
    run_index: number
    /**
     * When the turn completed.
     * @nullable
     */
    completed_at: string | null
    /** The turn's valid findings at must_fix priority. */
    must_fix_count: number
    /** The turn's valid findings at should_fix priority. */
    should_fix_count: number
    /** The turn's valid findings at consider priority. */
    consider_count: number
    /** Whether the turn was published to GitHub. */
    turn_published: boolean
    /**
     * Link to the review's status comment on the pull request; null when there is none.
     * @nullable
     */
    status_comment_url: string | null
}

/**
 * * `pending` - Pending
 * * `completed` - Completed
 * * `skipped` - Skipped
 * * `failed` - Failed
 * * `unknown` - Unknown
 */
export type ReviewRequestOutcomeStatusEnumApi =
    (typeof ReviewRequestOutcomeStatusEnumApi)[keyof typeof ReviewRequestOutcomeStatusEnumApi]

export const ReviewRequestOutcomeStatusEnumApi = {
    Pending: 'pending',
    Completed: 'completed',
    Skipped: 'skipped',
    Failed: 'failed',
    Unknown: 'unknown',
} as const

export interface ReviewPRStatusRequestOutcomeApi {
    /** How the request ended: 'pending' while a run for it is queued or running, 'completed' when a turn of the requested mode or deeper finished after `requested_at` and either started after it or reviewed the given `head_sha` (Deep covers Standard), 'skipped' when the run ended without doing the work, 'failed' when the run died or no run answered the request, 'unknown' when the run state could not be read (retry later).
     *
     * * `pending` - Pending
     * * `completed` - Completed
     * * `skipped` - Skipped
     * * `failed` - Failed
     * * `unknown` - Unknown */
    status: ReviewRequestOutcomeStatusEnumApi
    /**
     * Why it was skipped or failed: 'flash_after_full' (Standard dropped after a Deep review), 'review_failed', 'stopped' (Resolve died partway), 'no_matching_run' (nothing ran for the request and nothing is queued, for example when the queue replaced it), or a Resolve skip reason such as 'pr_not_open', 'resolution_not_opted_in', 'no_unresolved_threads', 'pr_in_merge_queue'. Null otherwise.
     * @nullable
     */
    reason: string | null
    /**
     * The review to read with `review-hog-reviews-get`; null before the PR has one.
     * @nullable
     */
    review_id: string | null
    /**
     * The review turn that answered or failed the request, for `review-hog-reviews-get`. Null for 'resolve_only' and while pending.
     * @nullable
     */
    run_index: number | null
}

export interface ReviewPRStatusApi {
    /** The pull request's repository as 'owner/repo'. */
    repository: string
    /** The pull request number. */
    pr_number: number
    /**
     * The PR's review id, for `review-hog-reviews-get`; null before its first run.
     * @nullable
     */
    report_id: string | null
    /** Where the PR stands now: 'not_reviewed' (no completed review and nothing queued), 'queued' (a run is queued or starting), 'reviewing' (a review turn is running), 'resolving' (Resolve is running), 'idle' (nothing running), 'unknown' (the run state could not be read, retry later).
     *
     * * `not_reviewed` - Not reviewed
     * * `queued` - Queued
     * * `reviewing` - Reviewing
     * * `resolving` - Resolving
     * * `idle` - Idle
     * * `unknown` - Unknown */
    state: ReviewPRStateEnumApi
    /** The latest completed review turn; null before the first one completes. */
    latest_review: ReviewPRStatusLatestReviewApi | null
    /** The latest Resolve run, finished ones too; null when no Resolve run has queued threads. */
    latest_resolution: ReviewLatestResolutionApi | null
    /** How the request at `requested_at` ended; null without `requested_at`. */
    request_outcome: ReviewPRStatusRequestOutcomeApi | null
}

export interface ReviewReviewsTablePageApi {
    /** How many reviews match the scope and every filter, across all pages. */
    count: number
    /** How many reviews have a run in flight under the scope and filters, ignoring `status`. Labels the running quick filter without a second request. */
    running_count: number
    /** One page of reviews, most recent activity first. */
    results: ReviewRecentReviewApi[]
}

/**
 * * `review` - Review
 * * `review_only` - Review only
 * * `resolve_only` - Resolve only
 * * `flash` - Standard
 */
export type ReviewTriggerRequestRunModeEnumApi =
    (typeof ReviewTriggerRequestRunModeEnumApi)[keyof typeof ReviewTriggerRequestRunModeEnumApi]

export const ReviewTriggerRequestRunModeEnumApi = {
    Review: 'review',
    ReviewOnly: 'review_only',
    ResolveOnly: 'resolve_only',
    Flash: 'flash',
} as const

export interface ReviewTriggerRequestApi {
    /** GitHub pull request URL to review, e.g. 'https://github.com/PostHog/posthog.com/pull/123'. The repository must be accessible to the project's GitHub App installation. */
    pr_url: string
    /** What to run on the pull request. 'review' (default) reviews it and, when the pull request owner's resolve_comments setting is on, chains the resolution stage; 'review_only' reviews without resolving regardless of that setting; 'resolve_only' skips the review and only runs the resolution stage on the PR's existing unresolved review threads, which needs the owner's opt-in; 'flash' runs a Standard review: a lower-cost model for the review passes and validation, never resolves comments, and is refused once the PR has a published Deep review. The owner is the PR's author, or the Inbox reviewer of a pull request the PostHog app opened.
     *
     * * `review` - Review
     * * `review_only` - Review only
     * * `resolve_only` - Resolve only
     * * `flash` - Standard */
    run_mode?: ReviewTriggerRequestRunModeEnumApi
}

/**
 * * `run_mode_excludes_resolve` - The run mode never resolves comments
 * * `owner_not_opted_in` - The pull request owner has not opted in to resolution
 * * `already_reviewed` - No run starts, because the head already has a review in this mode
 */
export type ResolveSkipReasonEnumApi = (typeof ResolveSkipReasonEnumApi)[keyof typeof ResolveSkipReasonEnumApi]

export const ResolveSkipReasonEnumApi = {
    RunModeExcludesResolve: 'run_mode_excludes_resolve',
    OwnerNotOptedIn: 'owner_not_opted_in',
    AlreadyReviewed: 'already_reviewed',
} as const

export interface ReviewTriggerResponseApi {
    /** Temporal workflow id for the started review run; empty when no run was started. */
    workflow_id: string
    /** Run lifecycle marker: 'started' when the review was queued, 'already_reviewed' when the pull request's current commit already has a published review in the requested mode, 'joined_running_review' when a review was already running and the request was queued on that pull request's run, to start after the running turn. A requested Deep review waits for an active Standard review. */
    status: string
    /** The pull request's repository as 'owner/repo'. */
    repository: string
    /** The pull request number. */
    pr_number: number
    /**
     * The pull request's head commit when the request was accepted.
     * @nullable
     */
    head_sha: string | null
    /** The review this request runs: 'full' (Deep) or 'flash' (Standard). Null for 'resolve_only', which runs no review.
     *
     * * `full` - Deep
     * * `flash` - Standard */
    review_mode: ReviewTriggerReviewModeEnumApi | null
    /**
     * Id of the pull request's existing review, for `review-hog-reviews-get`. Null on the pull request's first run, which creates the review later.
     * @nullable
     */
    report_id: string | null
    /** Server time when the request was accepted. */
    requested_at: string
    /** Whether this request plans to run the resolution stage, which can push fix commits to the pull request. It is the plan at request time: a request queued behind a running turn on the same head can be skipped as already published. `review-hog-reviews-pr-status` reports what actually ran. */
    resolve_will_run: boolean
    /** Why the resolution stage does not run: 'run_mode_excludes_resolve' ('review_only' and 'flash' never resolve), 'owner_not_opted_in' (the pull request owner has not turned on resolving comments), 'already_reviewed' (no run starts). Null when it runs.
     *
     * * `run_mode_excludes_resolve` - The run mode never resolves comments
     * * `owner_not_opted_in` - The pull request owner has not opted in to resolution
     * * `already_reviewed` - No run starts, because the head already has a review in this mode */
    resolve_skip_reason: ResolveSkipReasonEnumApi | null
}

/**
 * * `flash_after_full` - Standard after a published Deep review
 * * `resolution_not_opted_in` - The pull request owner has not opted in to resolution
 */
export type ReviewRequestRefusalEnumApi = (typeof ReviewRequestRefusalEnumApi)[keyof typeof ReviewRequestRefusalEnumApi]

export const ReviewRequestRefusalEnumApi = {
    FlashAfterFull: 'flash_after_full',
    ResolutionNotOptedIn: 'resolution_not_opted_in',
} as const

export interface ReviewTriggerErrorApi {
    /** Human-readable explanation of why the trigger was rejected. */
    error: string
    /** Why the request was refused, for a client that shows its own reason: 'flash_after_full' (the PR already has a published Deep review), 'resolution_not_opted_in' (the PR owner has not turned on resolving comments). Absent for other errors.
     *
     * * `flash_after_full` - Standard after a published Deep review
     * * `resolution_not_opted_in` - The pull request owner has not opted in to resolution */
    code?: ReviewRequestRefusalEnumApi
}

/**
 * * `follow` - Let each repository decide
 * * `flash` - On everywhere
 * * `off` - Off everywhere
 */
export type DefaultReviewModeEnumApi = (typeof DefaultReviewModeEnumApi)[keyof typeof DefaultReviewModeEnumApi]

export const DefaultReviewModeEnumApi = {
    Follow: 'follow',
    Flash: 'flash',
    Off: 'off',
} as const

/**
 * * `user` - Set by the user
 * * `project` - Project default
 * * `default` - Built-in default
 */
export type PreferenceSourceEnumApi = (typeof PreferenceSourceEnumApi)[keyof typeof PreferenceSourceEnumApi]

export const PreferenceSourceEnumApi = {
    User: 'user',
    Project: 'project',
    Default: 'default',
} as const

export interface ReviewPreferenceSourcesApi {
    /** Where the effective default_review_mode comes from: 'user' (the user set it), 'project' (the project default), or 'default' (the built-in default).
     *
     * * `user` - Set by the user
     * * `project` - Project default
     * * `default` - Built-in default */
    default_review_mode: PreferenceSourceEnumApi
    /** Where the effective resolve_comments comes from: 'user' (the user set it), 'project' (the project default), or 'default' (the built-in default).
     *
     * * `user` - Set by the user
     * * `project` - Project default
     * * `default` - Built-in default */
    resolve_comments: PreferenceSourceEnumApi
    /** Where the effective urgency_threshold comes from: 'user' (the user set it), 'project' (the project default), or 'default' (the built-in default).
     *
     * * `user` - Set by the user
     * * `project` - Project default
     * * `default` - Built-in default */
    urgency_threshold: PreferenceSourceEnumApi
    /** Where the effective celebrate_clean_reviews comes from: 'user' (the user set it), 'project' (the project default), or 'default' (the built-in default).
     *
     * * `user` - Set by the user
     * * `project` - Project default
     * * `default` - Built-in default */
    celebrate_clean_reviews: PreferenceSourceEnumApi
    /** Where the effective review_inbox_prs comes from: 'user' (the user set it), 'project' (the project default), or 'default' (the built-in default).
     *
     * * `user` - Set by the user
     * * `project` - Project default
     * * `default` - Built-in default */
    review_inbox_prs: PreferenceSourceEnumApi
    /** Where the effective stamphog_review_inbox_prs comes from: 'user' (the user set it), 'project' (the project default), or 'default' (the built-in default).
     *
     * * `user` - Set by the user
     * * `project` - Project default
     * * `default` - Built-in default */
    stamphog_review_inbox_prs: PreferenceSourceEnumApi
}

export interface ReviewProjectDefaultsApi {
    /** The project's default for the minimum priority a Deep review publishes.
     *
     * * `consider` - Consider (all)
     * * `should_fix` - Should fix
     * * `must_fix` - Must fix */
    urgency_threshold: UrgencyThresholdEnumApi
    /** The project's default for the image in a Deep review that finds nothing to raise. */
    celebrate_clean_reviews: boolean
}

export interface ReviewUserSettingsApi {
    /** Automatic reviews of the user's own pull requests in every repository this project reviews: 'follow' (default) uses each repository's rule, 'flash' gives automatic Standard reviews everywhere, and 'off' turns automatic reviews off everywhere. A choice for one repository wins over this default.
     *
     * * `follow` - Let each repository decide
     * * `flash` - On everywhere
     * * `off` - Off everywhere */
    default_review_mode?: DefaultReviewModeEnumApi
    /** After a Deep review of the user's pull requests is published, run the resolution stage: triage the unresolved review threads, implement the worth-and-safe fixes on the PR branch, and reply on every thread. Off by default. Personal only: no project default applies. */
    resolve_comments?: boolean
    /** Minimum priority a validated Deep review finding needs to be published: 'consider' publishes everything, 'should_fix' drops consider-level findings, 'must_fix' publishes only blocking issues. Without the user's own value the project default applies.
     *
     * * `consider` - Consider (all)
     * * `should_fix` - Should fix
     * * `must_fix` - Must fix */
    urgency_threshold?: UrgencyThresholdEnumApi
    /** Show a fun image in the review comment when a Deep review of the user's pull requests finds nothing to raise. Without the user's own value the project default applies. */
    celebrate_clean_reviews?: boolean
    /** Review the pull requests the agent opens for Inbox reports assigned to the user: ReviewHog reviews each one and posts its findings to the pull request. Off by default. */
    review_inbox_prs?: boolean
    /** Also have hosted Stamphog review those same Inbox pull requests: an approve-first review that posts a real GitHub approval when the change passes, and a comment when it doesn't. Only takes effect when the project has a synced, enabled Stamphog repository (see stamphog_connected). */
    stamphog_review_inbox_prs?: boolean
    /** Where each effective value comes from. A value equal to the inherited one is never stored, so writing the project default or the built-in default makes the source follow it again. */
    readonly sources: ReviewPreferenceSourcesApi
    /** The project defaults the Deep review preferences fall back to. */
    readonly project_defaults: ReviewProjectDefaultsApi
    /** Whether this project has at least one synced, enabled Stamphog repository. When false, the stamphog_review_inbox_prs toggle has nothing to act on and the UI renders it disabled with a pointer to connect the Stamphog GitHub App. */
    readonly stamphog_connected: boolean
}

export interface PatchedReviewUserSettingsApi {
    /** Automatic reviews of the user's own pull requests in every repository this project reviews: 'follow' (default) uses each repository's rule, 'flash' gives automatic Standard reviews everywhere, and 'off' turns automatic reviews off everywhere. A choice for one repository wins over this default.
     *
     * * `follow` - Let each repository decide
     * * `flash` - On everywhere
     * * `off` - Off everywhere */
    default_review_mode?: DefaultReviewModeEnumApi
    /** After a Deep review of the user's pull requests is published, run the resolution stage: triage the unresolved review threads, implement the worth-and-safe fixes on the PR branch, and reply on every thread. Off by default. Personal only: no project default applies. */
    resolve_comments?: boolean
    /** Minimum priority a validated Deep review finding needs to be published: 'consider' publishes everything, 'should_fix' drops consider-level findings, 'must_fix' publishes only blocking issues. Without the user's own value the project default applies.
     *
     * * `consider` - Consider (all)
     * * `should_fix` - Should fix
     * * `must_fix` - Must fix */
    urgency_threshold?: UrgencyThresholdEnumApi
    /** Show a fun image in the review comment when a Deep review of the user's pull requests finds nothing to raise. Without the user's own value the project default applies. */
    celebrate_clean_reviews?: boolean
    /** Review the pull requests the agent opens for Inbox reports assigned to the user: ReviewHog reviews each one and posts its findings to the pull request. Off by default. */
    review_inbox_prs?: boolean
    /** Also have hosted Stamphog review those same Inbox pull requests: an approve-first review that posts a real GitHub approval when the change passes, and a comment when it doesn't. Only takes effect when the project has a synced, enabled Stamphog repository (see stamphog_connected). */
    stamphog_review_inbox_prs?: boolean
    /** Where each effective value comes from. A value equal to the inherited one is never stored, so writing the project default or the built-in default makes the source follow it again. */
    readonly sources?: ReviewPreferenceSourcesApi
    /** The project defaults the Deep review preferences fall back to. */
    readonly project_defaults?: ReviewProjectDefaultsApi
    /** Whether this project has at least one synced, enabled Stamphog repository. When false, the stamphog_review_inbox_prs toggle has nothing to act on and the UI renders it disabled with a pointer to connect the Stamphog GitHub App. */
    readonly stamphog_connected?: boolean
}

export interface ReviewValidatorConfigApi {
    /** Name of the `review-hog-validation-*` skill this row represents (the validator's identity). */
    skill_name: string
    /** Whether this validator is the one that validates the requesting user's PR reviews on this project. */
    active: boolean
    /** The validator skill's description, for display in the config UI. */
    description: string
    /** The validator skill's SKILL.md body, for the read-only skill viewer. */
    body: string
}

export interface PatchedReviewValidatorConfigSelectApi {
    /** Set true to make this the single validator that runs on the user's PR reviews. Only true is accepted — validators are single-active, so you switch by selecting a different one, not by deactivating the current one. */
    active?: boolean
}

export type ReviewHogRepositoryOverviewRetrieveParams = {
    /**
     * The GitHub App installation to list.
     * @minLength 1
     * @maxLength 64
     */
    installation_id: string
    /**
     * Entries per page (max 200).
     * @minimum 1
     * @maximum 200
     */
    limit?: number
    /**
     * Entries to skip.
     * @minimum 0
     */
    offset?: number
    /**
     * Only repositories whose name contains this text.
     */
    search?: string
    /**
     * 'all' repositories, 'in_project' (reviewed by this project), 'exceptions' (with a repository exception), or 'mine' (with the requesting user's own choice).
     *
     * * `all` - All repositories
     * * `in_project` - In this project
     * * `exceptions` - With exceptions
     * * `mine` - My choices
     * @minLength 1
     */
    view?: ReviewHogRepositoryOverviewRetrieveView
}

export type ReviewHogRepositoryOverviewRetrieveView =
    (typeof ReviewHogRepositoryOverviewRetrieveView)[keyof typeof ReviewHogRepositoryOverviewRetrieveView]

export const ReviewHogRepositoryOverviewRetrieveView = {
    All: 'all',
    InProject: 'in_project',
    Exceptions: 'exceptions',
    Mine: 'mine',
} as const

export type ReviewHogReviewsListParams = {
    /**
     * Maximum rows to return. The list grows this instead of paging by offset — in-progress rows reorder the list between refreshes, so offset pages would shift under the reader.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Whose reviews to list: `mine` (the default) for reviews the requesting user ran plus reviews of pull requests they authored (matched via their linked GitHub login), `everyone` for every review on this project.
     *
     * * `mine` - mine
     * * `everyone` - everyone
     * @minLength 1
     */
    scope?: ReviewHogReviewsListScope
}

export type ReviewHogReviewsListScope = (typeof ReviewHogReviewsListScope)[keyof typeof ReviewHogReviewsListScope]

export const ReviewHogReviewsListScope = {
    Mine: 'mine',
    Everyone: 'everyone',
} as const

export type ReviewHogReviewsRetrieveParams = {
    /**
     * The completed review turn to read, from 1 to `run_count`. Defaults to the latest completed turn. Use it to read an older turn's findings.
     */
    run_index?: number
}

export type ReviewHogReviewsPerspectiveStatsRetrieveParams = {
    /**
     * Whose reviews to aggregate: `mine` (the default) for reviews the requesting user ran plus reviews of pull requests they authored (matched via their linked GitHub login), `everyone` for every review on this project, `own_deep` for the last 10 Deep reviews the requesting user started. The review skills in the settings use `own_deep`, because only the person who starts a Deep review picks its skills.
     *
     * * `mine` - Mine
     * * `everyone` - Everyone
     * * `own_deep` - Own Deep reviews
     * @minLength 1
     */
    scope?: ReviewHogReviewsPerspectiveStatsRetrieveScope
}

export type ReviewHogReviewsPerspectiveStatsRetrieveScope =
    (typeof ReviewHogReviewsPerspectiveStatsRetrieveScope)[keyof typeof ReviewHogReviewsPerspectiveStatsRetrieveScope]

export const ReviewHogReviewsPerspectiveStatsRetrieveScope = {
    Mine: 'mine',
    Everyone: 'everyone',
    OwnDeep: 'own_deep',
} as const

export type ReviewHogReviewsPrStatusRetrieveParams = {
    /**
     * The `head_sha` the trigger returned. Lets a turn that was already running on that head when the request came in answer the request. Only used with `requested_at`.
     * @minLength 1
     */
    head_sha?: string
    /**
     * GitHub pull request URL to look up, e.g. 'https://github.com/PostHog/posthog/pull/123'.
     * @minLength 1
     */
    pr_url: string
    /**
     * The `requested_at` the trigger returned. When set, the response carries `request_outcome` for that request.
     */
    requested_at?: string
    /**
     * The `run_mode` the trigger was called with (default 'review'). Only used with `requested_at`.
     *
     * * `review` - Review
     * * `review_only` - Review only
     * * `resolve_only` - Resolve only
     * * `flash` - Standard
     * @minLength 1
     */
    run_mode?: ReviewHogReviewsPrStatusRetrieveRunMode
}

export type ReviewHogReviewsPrStatusRetrieveRunMode =
    (typeof ReviewHogReviewsPrStatusRetrieveRunMode)[keyof typeof ReviewHogReviewsPrStatusRetrieveRunMode]

export const ReviewHogReviewsPrStatusRetrieveRunMode = {
    Review: 'review',
    ReviewOnly: 'review_only',
    ResolveOnly: 'resolve_only',
    Flash: 'flash',
} as const

export type ReviewHogReviewsTableRetrieveParams = {
    /**
     * Rows per page. Defaults to 25, at most 100.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * How many rows to skip, for paging through the table.
     * @minimum 0
     */
    offset?: number
    /**
     * Only reviews whose latest completed turn was (true) or was not (false) published to GitHub.
     * @nullable
     */
    published?: boolean | null
    /**
     * Only reviews of this repository, as `owner/repo`. Matched case-insensitively.
     * @minLength 1
     */
    repository?: string
    /**
     * Only reviews whose latest completed turn ran this mode: 'full' (Deep) or 'flash' (Standard). Turns that did not record their mode match neither value.
     *
     * * `full` - Deep
     * * `flash` - Standard
     * @minLength 1
     */
    review_mode?: ReviewHogReviewsTableRetrieveReviewMode
    /**
     * Whose reviews to list: `mine` (the default) for reviews the requesting user ran plus reviews of pull requests they authored (matched via their linked GitHub login), `everyone` for every review on this project.
     *
     * * `mine` - Mine
     * * `everyone` - Everyone
     * @minLength 1
     */
    scope?: ReviewHogReviewsTableRetrieveScope
    /**
     * Only reviews in this state: 'running' for reviews with a run in flight (activity within the last 30 minutes), 'completed' for reviews with a completed turn and nothing running now.
     *
     * * `running` - Running
     * * `completed` - Completed
     * @minLength 1
     */
    status?: ReviewHogReviewsTableRetrieveStatus
}

export type ReviewHogReviewsTableRetrieveReviewMode =
    (typeof ReviewHogReviewsTableRetrieveReviewMode)[keyof typeof ReviewHogReviewsTableRetrieveReviewMode]

export const ReviewHogReviewsTableRetrieveReviewMode = {
    Full: 'full',
    Flash: 'flash',
} as const

export type ReviewHogReviewsTableRetrieveScope =
    (typeof ReviewHogReviewsTableRetrieveScope)[keyof typeof ReviewHogReviewsTableRetrieveScope]

export const ReviewHogReviewsTableRetrieveScope = {
    Mine: 'mine',
    Everyone: 'everyone',
} as const

export type ReviewHogReviewsTableRetrieveStatus =
    (typeof ReviewHogReviewsTableRetrieveStatus)[keyof typeof ReviewHogReviewsTableRetrieveStatus]

export const ReviewHogReviewsTableRetrieveStatus = {
    Running: 'running',
    Completed: 'completed',
} as const
