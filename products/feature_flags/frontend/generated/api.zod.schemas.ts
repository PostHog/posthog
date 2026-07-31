/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const StaffCacheSourceEnumApi = zod.enum(['redis', 'miss']).describe('\* `redis` - redis\n\* `miss` - miss')

export type StaffCacheSourceEnumApi = zod.input<typeof StaffCacheSourceEnumApi>
export type StaffCacheSourceEnumApiOutput = zod.output<typeof StaffCacheSourceEnumApi>

export const StaffCacheEntryStatusApi = zod.object({
    source: StaffCacheSourceEnumApi.describe(
        "'redis' when a warm entry is cached, or 'miss' when nothing is cached in Redis.\n\n\* `redis` - redis\n\* `miss` - miss"
    ),
    flag_count: zod.number().nullable().describe('Number of flags in the cached payload, or null on a miss.'),
})

export type StaffCacheEntryStatusApi = zod.input<typeof StaffCacheEntryStatusApi>
export type StaffCacheEntryStatusApiOutput = zod.output<typeof StaffCacheEntryStatusApi>

export const StaffCacheTeamStatusApi = zod.object({
    team_id: zod.number().describe('Team id.'),
    evaluation: StaffCacheEntryStatusApi.describe('Status of the \/flags evaluation cache.'),
    definitions: StaffCacheEntryStatusApi.describe('Status of the \/flags\/definitions local-eval cache.'),
})

export type StaffCacheTeamStatusApi = zod.input<typeof StaffCacheTeamStatusApi>
export type StaffCacheTeamStatusApiOutput = zod.output<typeof StaffCacheTeamStatusApi>

export const StaffCacheStatusResponseApi = zod.object({
    results: zod.array(StaffCacheTeamStatusApi).describe('Per-team cache status.'),
})

export type StaffCacheStatusResponseApi = zod.input<typeof StaffCacheStatusResponseApi>
export type StaffCacheStatusResponseApiOutput = zod.output<typeof StaffCacheStatusResponseApi>

export const StaffCacheKindEnumApi = zod
    .enum(['evaluation', 'definitions'])
    .describe('\* `evaluation` - evaluation\n\* `definitions` - definitions')

export type StaffCacheKindEnumApi = zod.input<typeof StaffCacheKindEnumApi>
export type StaffCacheKindEnumApiOutput = zod.output<typeof StaffCacheKindEnumApi>

export const staffCacheMutationApiTeamIdsMax = 50

export const staffCacheMutationApiCachesDefault = [`evaluation`, `definitions`]

export const StaffCacheMutationApi = zod.object({
    team_ids: zod
        .array(zod.number())
        .max(staffCacheMutationApiTeamIdsMax)
        .describe('Team ids to act on (max 50 per request).'),
    caches: zod
        .array(StaffCacheKindEnumApi)
        .default(staffCacheMutationApiCachesDefault)
        .describe(
            "Which logical caches to act on: 'evaluation' (the \/flags cache) and\/or 'definitions' (the \/flags\/definitions local-eval cache). Defaults to both."
        ),
})

export type StaffCacheMutationApi = zod.input<typeof StaffCacheMutationApi>
export type StaffCacheMutationApiOutput = zod.output<typeof StaffCacheMutationApi>

export const StaffCacheMutationResponseApi = zod.object({
    queued_team_ids: zod.array(zod.number()).describe("Team ids for which the requested action's tasks were enqueued."),
    not_found_team_ids: zod.array(zod.number()).describe('Requested team ids that do not exist.'),
})

export type StaffCacheMutationResponseApi = zod.input<typeof StaffCacheMutationResponseApi>
export type StaffCacheMutationResponseApiOutput = zod.output<typeof StaffCacheMutationResponseApi>

export const StaffCacheEntryResponseApi = zod.object({
    team_id: zod.number().describe('Team id.'),
    cache: StaffCacheKindEnumApi.describe(
        'Which cache this entry is for.\n\n\* `evaluation` - evaluation\n\* `definitions` - definitions'
    ),
    source: StaffCacheSourceEnumApi.describe(
        "'redis' when a warm entry is cached, or 'miss' when nothing is cached in Redis.\n\n\* `redis` - redis\n\* `miss` - miss"
    ),
    data: zod
        .record(zod.string(), zod.unknown())
        .nullable()
        .describe('Raw cached payload as stored in Redis, or null on a miss.'),
})

export type StaffCacheEntryResponseApi = zod.input<typeof StaffCacheEntryResponseApi>
export type StaffCacheEntryResponseApiOutput = zod.output<typeof StaffCacheEntryResponseApi>

export const FlagsWarmRunStateEnumApi = zod
    .enum(['running', 'completed', 'cancelled'])
    .describe('\* `running` - running\n\* `completed` - completed\n\* `cancelled` - cancelled')

export type FlagsWarmRunStateEnumApi = zod.input<typeof FlagsWarmRunStateEnumApi>
export type FlagsWarmRunStateEnumApiOutput = zod.output<typeof FlagsWarmRunStateEnumApi>

export const FlagsWarmRunScopeEnumApi = zod
    .enum(['all_teams', 'teams_with_flags'])
    .describe('\* `all_teams` - all_teams\n\* `teams_with_flags` - teams_with_flags')

export type FlagsWarmRunScopeEnumApi = zod.input<typeof FlagsWarmRunScopeEnumApi>
export type FlagsWarmRunScopeEnumApiOutput = zod.output<typeof FlagsWarmRunScopeEnumApi>

export const StaffWarmRunApi = zod.object({
    run_id: zod.string().describe('Unique id of the warm-all run.'),
    state: FlagsWarmRunStateEnumApi.describe(
        "'running' while the warmer is working, 'completed' when it finished (per-team failures are counted, not fatal), or 'cancelled' when a cancel request was honored.\n\n\* `running` - running\n\* `completed` - completed\n\* `cancelled` - cancelled"
    ),
    scope: FlagsWarmRunScopeEnumApi.describe(
        'Which teams the run covers: every team, or only teams that have ever had a flag.\n\n\* `all_teams` - all_teams\n\* `teams_with_flags` - teams_with_flags'
    ),
    total: zod.number().describe('Number of teams the run will warm.'),
    processed: zod.number().describe('Teams processed so far (successful + failed).'),
    successful: zod.number().describe('Teams whose evaluation cache was rebuilt successfully.'),
    failed: zod.number().describe("Teams whose rebuild failed; details are in the warmer's logs."),
    last_team_id: zod
        .number()
        .nullable()
        .describe('Highest team id dispatched so far — a resume cursor for operators re-running the warmer.'),
    started_at: zod.iso.datetime({ offset: true }).describe('When the run started.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('Heartbeat: last time the warmer reported progress.'),
    is_stale: zod
        .boolean()
        .describe(
            'True when the run claims to be running but its heartbeat stopped — the warmer process likely died without writing a final state.'
        ),
    cancel_requested: zod
        .boolean()
        .describe('True when a cancel has been requested for this run but the warmer has not yet honored it.'),
})

export type StaffWarmRunApi = zod.input<typeof StaffWarmRunApi>
export type StaffWarmRunApiOutput = zod.output<typeof StaffWarmRunApi>

export const StaffWarmRunResponseApi = zod.object({
    run: zod
        .union([StaffWarmRunApi, zod.null()])
        .describe(
            'Most recent warm-all run, or null when none has been recorded (or the dedicated flags cache is not configured).'
        ),
})

export type StaffWarmRunResponseApi = zod.input<typeof StaffWarmRunResponseApi>
export type StaffWarmRunResponseApiOutput = zod.output<typeof StaffWarmRunResponseApi>

export const StaffWarmRunCancelResponseApi = zod.object({
    run_id: zod.string().describe('Id of the run the cancel request targets.'),
    cancel_requested: zod.boolean().describe('Always true on success.'),
})

export type StaffWarmRunCancelResponseApi = zod.input<typeof StaffWarmRunCancelResponseApi>
export type StaffWarmRunCancelResponseApiOutput = zod.output<typeof StaffWarmRunCancelResponseApi>

export const StaffTeamConfigApi = zod.object({
    team_id: zod.number().describe('Team id.'),
    minimal_flag_called_events: zod
        .boolean()
        .describe(
            "Whether this team's SDKs receive the slim $feature_flag_called event shape (omitting fields only needed for experiments) instead of the full legacy shape."
        ),
})

export type StaffTeamConfigApi = zod.input<typeof StaffTeamConfigApi>
export type StaffTeamConfigApiOutput = zod.output<typeof StaffTeamConfigApi>

export const StaffTeamConfigListResponseApi = zod.object({
    results: zod.array(StaffTeamConfigApi).describe('Per-team feature-flags config.'),
})

export type StaffTeamConfigListResponseApi = zod.input<typeof StaffTeamConfigListResponseApi>
export type StaffTeamConfigListResponseApiOutput = zod.output<typeof StaffTeamConfigListResponseApi>

export const StaffTeamConfigMutationApi = zod.object({
    team_id: zod.number().describe('Team id to update. Exactly one team per request.'),
    minimal_flag_called_events: zod
        .boolean()
        .describe(
            "New value for the team's minimal_flag_called_events setting. Only set true after confirming that team's SDK versions support the slim $feature_flag_called event shape."
        ),
})

export type StaffTeamConfigMutationApi = zod.input<typeof StaffTeamConfigMutationApi>
export type StaffTeamConfigMutationApiOutput = zod.output<typeof StaffTeamConfigMutationApi>

export const StaffTeamResultApi = zod.object({
    id: zod.number().describe('Team id.'),
    name: zod.string().describe('Team name.'),
    api_token: zod.string().describe('Team api_token (used as the flags evaluation cache key).'),
    organization_id: zod.string().describe('Organization uuid that owns the team.'),
    organization_name: zod.string().describe('Organization name that owns the team.'),
    project_id: zod.number().describe('Project id the team belongs to.'),
})

export type StaffTeamResultApi = zod.input<typeof StaffTeamResultApi>
export type StaffTeamResultApiOutput = zod.output<typeof StaffTeamResultApi>

export const StaffTeamSearchResponseApi = zod.object({
    results: zod.array(StaffTeamResultApi).describe('Matching teams.'),
})

export type StaffTeamSearchResponseApi = zod.input<typeof StaffTeamSearchResponseApi>
export type StaffTeamSearchResponseApiOutput = zod.output<typeof StaffTeamSearchResponseApi>

export const copyFlagsRequestApiTargetProjectIdsMax = 50

export const copyFlagsRequestApiCopyScheduleDefault = false
export const copyFlagsRequestApiDisableCopiedFlagDefault = false
export const copyFlagsRequestApiCopyDependenciesDefault = false

export const CopyFlagsRequestApi = zod.object({
    feature_flag_key: zod.string().describe('Key of the feature flag to copy'),
    from_project: zod.number().describe('Source project ID to copy the flag from'),
    target_project_ids: zod
        .array(zod.number())
        .min(1)
        .max(copyFlagsRequestApiTargetProjectIdsMax)
        .describe('List of target project IDs to copy the flag to'),
    copy_schedule: zod
        .boolean()
        .default(copyFlagsRequestApiCopyScheduleDefault)
        .describe('Whether to also copy scheduled changes for this flag'),
    disable_copied_flag: zod
        .boolean()
        .default(copyFlagsRequestApiDisableCopiedFlagDefault)
        .describe(
            "Whether to force the copied flag to be disabled in target projects, ignoring the source flag's enabled status"
        ),
    copy_dependencies: zod
        .boolean()
        .default(copyFlagsRequestApiCopyDependenciesDefault)
        .describe('Whether to also copy missing feature flags that this flag depends on'),
})

export type CopyFlagsRequestApi = zod.input<typeof CopyFlagsRequestApi>
export type CopyFlagsRequestApiOutput = zod.output<typeof CopyFlagsRequestApi>

export const CopyFlagsSuccessItemApi = zod.object({
    id: zod.number().describe('ID of the created feature flag'),
    key: zod.string().describe('Key of the feature flag'),
    name: zod.string().describe('Name of the feature flag'),
    active: zod.boolean().describe('Whether the flag is active'),
    team_id: zod.number().describe('Team ID the flag was copied to'),
    updated_existing: zod
        .boolean()
        .describe(
            'True when a flag with the same key already existed in the target project and was overwritten with the copied configuration, false when a new flag was created'
        ),
    flag_dependency_warnings: zod
        .array(zod.string())
        .optional()
        .describe(
            'Warnings for flag dependencies that were dropped because no matching active flag exists in the target project'
        ),
    schedule_copy_warning: zod
        .string()
        .optional()
        .describe(
            'Warning emitted when schedules failed to copy or existing target schedules may affect the copied flag'
        ),
    copied_dependency_keys: zod
        .array(zod.string())
        .optional()
        .describe('Dependency flag keys that were copied before this flag'),
    dependency_copy_warnings: zod
        .array(zod.string())
        .optional()
        .describe('Warnings emitted while copying dependency flags'),
})

export type CopyFlagsSuccessItemApi = zod.input<typeof CopyFlagsSuccessItemApi>
export type CopyFlagsSuccessItemApiOutput = zod.output<typeof CopyFlagsSuccessItemApi>

export const CopyFlagsResultApi = zod.object({
    project_id: zod.number().optional().describe('Project ID (present on failure)'),
    error_message: zod.string().optional().describe('Error message (present on failure)'),
    approval_pending: zod
        .boolean()
        .optional()
        .describe(
            "True when the copy was not applied because the target project's approval policy requires approval; a change request has been created and the copy will apply once approved"
        ),
    change_request_id: zod
        .string()
        .optional()
        .describe(
            'ID of the pending change request created in the target project (present when approval_pending is true)'
        ),
})

export type CopyFlagsResultApi = zod.input<typeof CopyFlagsResultApi>
export type CopyFlagsResultApiOutput = zod.output<typeof CopyFlagsResultApi>

export const CopyFlagsResponseApi = zod.object({
    success: zod.array(CopyFlagsSuccessItemApi).describe('List of successfully copied flags'),
    failed: zod.array(CopyFlagsResultApi).describe('List of failed copy attempts'),
})

export type CopyFlagsResponseApi = zod.input<typeof CopyFlagsResponseApi>
export type CopyFlagsResponseApiOutput = zod.output<typeof CopyFlagsResponseApi>

export const ErrorResponseApi = zod.object({
    error: zod.string().describe('Error message'),
})

export type ErrorResponseApi = zod.input<typeof ErrorResponseApi>
export type ErrorResponseApiOutput = zod.output<typeof ErrorResponseApi>

export const copyFlagsDependencyRequirementsRequestApiTargetProjectIdsMax = 50

export const CopyFlagsDependencyRequirementsRequestApi = zod.object({
    feature_flag_key: zod.string().describe('Key of the feature flag to check'),
    from_project: zod.number().describe('Source project ID to copy the flag from'),
    target_project_ids: zod
        .array(zod.number())
        .min(1)
        .max(copyFlagsDependencyRequirementsRequestApiTargetProjectIdsMax)
        .describe('List of target project IDs to check dependency copy eligibility for'),
})

export type CopyFlagsDependencyRequirementsRequestApi = zod.input<typeof CopyFlagsDependencyRequirementsRequestApi>
export type CopyFlagsDependencyRequirementsRequestApiOutput = zod.output<
    typeof CopyFlagsDependencyRequirementsRequestApi
>

export const CopyFlagsDependencyRequirementsResponseApi = zod.object({
    can_copy_dependencies: zod.boolean().describe('Whether dependencies can be automatically copied'),
    dependency_count: zod.number().describe('Total number of transitive source dependency flags'),
    copied_dependency_keys: zod
        .array(zod.string())
        .describe('Dependency flag keys that would be copied because they are missing from a target project'),
    reused_dependency_keys: zod
        .array(zod.string())
        .describe('Dependency flag keys that already have an active same-key flag in every target project'),
    warnings: zod.array(zod.string()).describe('Reasons dependency copying is unavailable or needs user attention'),
    reason: zod.string().describe('Primary human-readable eligibility result'),
})

export type CopyFlagsDependencyRequirementsResponseApi = zod.input<typeof CopyFlagsDependencyRequirementsResponseApi>
export type CopyFlagsDependencyRequirementsResponseApiOutput = zod.output<
    typeof CopyFlagsDependencyRequirementsResponseApi
>

export const OrganizationFeatureFlagRowApi = zod.object({
    id: zod.number().describe('ID of the representative feature flag for this key'),
    team_id: zod.number().describe('Team ID the representative feature flag belongs to'),
    key: zod.string().describe('Feature flag key, unique within the compared projects'),
    name: zod.string().describe('Human-readable name of the representative feature flag'),
    active: zod.boolean().describe('Whether the representative feature flag is enabled'),
    filters: zod.unknown().describe('Release condition filters of the representative feature flag'),
})

export type OrganizationFeatureFlagRowApi = zod.input<typeof OrganizationFeatureFlagRowApi>
export type OrganizationFeatureFlagRowApiOutput = zod.output<typeof OrganizationFeatureFlagRowApi>

export const OrganizationFeatureFlagKeysResponseApi = zod.object({
    count: zod.number().describe('Total number of distinct flag keys across the compared projects'),
    next: zod.string().nullable().describe('URL for the next page of results, or null if none'),
    previous: zod.string().nullable().describe('URL for the previous page of results, or null if none'),
    results: zod
        .array(OrganizationFeatureFlagRowApi)
        .describe('One representative flag per distinct key across the compared projects'),
})

export type OrganizationFeatureFlagKeysResponseApi = zod.input<typeof OrganizationFeatureFlagKeysResponseApi>
export type OrganizationFeatureFlagKeysResponseApiOutput = zod.output<typeof OrganizationFeatureFlagKeysResponseApi>

export const evaluationContextSuggestionRequestApiContextNameMax = 255

export const EvaluationContextSuggestionRequestApi = zod.object({
    context_name: zod
        .string()
        .max(evaluationContextSuggestionRequestApiContextNameMax)
        .describe(
            "Name of the evaluation context to hide from (POST) or restore to (DELETE) the flag editor's suggestion list. Case-insensitive and whitespace-trimmed."
        ),
})

export type EvaluationContextSuggestionRequestApi = zod.input<typeof EvaluationContextSuggestionRequestApi>
export type EvaluationContextSuggestionRequestApiOutput = zod.output<typeof EvaluationContextSuggestionRequestApi>

export const EvaluationContextSuggestionResponseApi = zod.object({
    success: zod.boolean().describe('Whether the suggestion visibility change was applied.'),
    name: zod.string().describe('Normalized name of the affected evaluation context.'),
    hidden_from_suggestions: zod
        .boolean()
        .describe("Whether the context is now hidden from the flag editor's suggestion list."),
})

export type EvaluationContextSuggestionResponseApi = zod.input<typeof EvaluationContextSuggestionResponseApi>
export type EvaluationContextSuggestionResponseApiOutput = zod.output<typeof EvaluationContextSuggestionResponseApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const FeatureFlagExperimentSetMetadataApi = zod.object({
    id: zod.number().describe('ID of the experiment linked to this flag.'),
    name: zod.string().describe('Name of the experiment linked to this flag.'),
    is_running: zod
        .boolean()
        .describe(
            'Whether the experiment is currently running (started and not yet stopped). A running experiment blocks deletion of the linked flag.'
        ),
})

export type FeatureFlagExperimentSetMetadataApi = zod.input<typeof FeatureFlagExperimentSetMetadataApi>
export type FeatureFlagExperimentSetMetadataApiOutput = zod.output<typeof FeatureFlagExperimentSetMetadataApi>

export const FeatureFlagCreationContextEnumApi = zod
    .enum(['feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'])
    .describe(
        '\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours'
    )

export type FeatureFlagCreationContextEnumApi = zod.input<typeof FeatureFlagCreationContextEnumApi>
export type FeatureFlagCreationContextEnumApiOutput = zod.output<typeof FeatureFlagCreationContextEnumApi>

export const EvaluationRuntimeEnumApi = zod
    .enum(['server', 'client', 'all'])
    .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All')

export type EvaluationRuntimeEnumApi = zod.input<typeof EvaluationRuntimeEnumApi>
export type EvaluationRuntimeEnumApiOutput = zod.output<typeof EvaluationRuntimeEnumApi>

export const BucketingIdentifierEnumApi = zod
    .enum(['distinct_id', 'device_id'])
    .describe('\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID')

export type BucketingIdentifierEnumApi = zod.input<typeof BucketingIdentifierEnumApi>
export type BucketingIdentifierEnumApiOutput = zod.output<typeof BucketingIdentifierEnumApi>

export const featureFlagApiKeyMax = 400

export const featureFlagApiVersionDefault = 0
export const featureFlagApiShouldCreateUsageDashboardDefault = true

export const FeatureFlagApi = zod
    .object({
        id: zod.number(),
        name: zod
            .string()
            .optional()
            .describe('contains the description for the flag (field name `name` is kept for backwards-compatibility)'),
        key: zod.string().max(featureFlagApiKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        archived: zod
            .boolean()
            .optional()
            .describe(
                'Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).'
            ),
        created_by: UserBasicApi,
        created_at: zod.iso.datetime({ offset: true }).optional(),
        updated_at: zod.iso.datetime({ offset: true }).nullable(),
        version: zod.number().default(featureFlagApiVersionDefault),
        last_modified_by: UserBasicApi,
        ensure_experience_continuity: zod.boolean().nullish(),
        experiment_set: zod.array(zod.number()),
        experiment_set_metadata: zod.array(FeatureFlagExperimentSetMetadataApi),
        surveys: zod.record(zod.string(), zod.unknown()),
        features: zod.record(zod.string(), zod.unknown()),
        can_edit: zod.boolean(),
        tags: zod.array(zod.unknown()).optional(),
        evaluation_contexts: zod.array(zod.unknown()).optional(),
        usage_dashboard: zod.number(),
        analytics_dashboards: zod.array(zod.number()).optional(),
        has_enriched_analytics: zod.boolean().nullish(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        creation_context: FeatureFlagCreationContextEnumApi.optional().describe(
            "Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.\n\n\* `feature_flags` - feature_flags\n\* `experiments` - experiments\n\* `surveys` - surveys\n\* `early_access_features` - early_access_features\n\* `web_experiments` - web_experiments\n\* `product_tours` - product_tours"
        ),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        status: zod.string(),
        evaluation_runtime: zod
            .union([EvaluationRuntimeEnumApi, BlankEnumApi, zod.null()])
            .optional()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
            ),
        bucketing_identifier: zod
            .union([BucketingIdentifierEnumApi, BlankEnumApi, zod.null()])
            .optional()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'
            ),
        last_called_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        _create_in_folder: zod.string().optional(),
        _should_create_usage_dashboard: zod.boolean().default(featureFlagApiShouldCreateUsageDashboardDefault),
        is_used_in_replay_settings: zod
            .boolean()
            .describe("Check if this feature flag is used in any team's session recording linked flag setting."),
        is_eligible_for_experiment: zod
            .boolean()
            .describe('Whether this flag can back an experiment: multivariate with 2 to 20 variants.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type FeatureFlagApi = zod.input<typeof FeatureFlagApi>
export type FeatureFlagApiOutput = zod.output<typeof FeatureFlagApi>

export const PaginatedFeatureFlagListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(FeatureFlagApi),
})

export type PaginatedFeatureFlagListApi = zod.input<typeof PaginatedFeatureFlagListApi>
export type PaginatedFeatureFlagListApiOutput = zod.output<typeof PaginatedFeatureFlagListApi>

export const PropertyGroupTypeEnumApi = zod
    .enum(['cohort', 'person', 'group'])
    .describe('\* `cohort` - cohort\n\* `person` - person\n\* `group` - group')

export type PropertyGroupTypeEnumApi = zod.input<typeof PropertyGroupTypeEnumApi>
export type PropertyGroupTypeEnumApiOutput = zod.output<typeof PropertyGroupTypeEnumApi>

export const FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi = zod
    .enum([
        'exact',
        'is_not',
        'icontains',
        'not_icontains',
        'starts_with',
        'not_starts_with',
        'ends_with',
        'not_ends_with',
        'regex',
        'not_regex',
        'gt',
        'gte',
        'lt',
        'lte',
    ])
    .describe(
        '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `gte` - gte\n\* `lt` - lt\n\* `lte` - lte'
    )

export type FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertyGenericSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertyGenericSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    value: zod
        .unknown()
        .describe('Comparison value for the property filter. Supports strings, numbers, booleans, and arrays.'),
    operator: FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi.describe(
        'Operator used to compare the property value.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `gte` - gte\n\* `lt` - lt\n\* `lte` - lte'
    ),
})

export type FeatureFlagFilterPropertyGenericSchemaApi = zod.input<typeof FeatureFlagFilterPropertyGenericSchemaApi>
export type FeatureFlagFilterPropertyGenericSchemaApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyGenericSchemaApi
>

export const ExistenceOperatorEnumApi = zod
    .enum(['is_set', 'is_not_set'])
    .describe('\* `is_set` - is_set\n\* `is_not_set` - is_not_set')

export type ExistenceOperatorEnumApi = zod.input<typeof ExistenceOperatorEnumApi>
export type ExistenceOperatorEnumApiOutput = zod.output<typeof ExistenceOperatorEnumApi>

export const FeatureFlagFilterPropertyExistsSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: ExistenceOperatorEnumApi.describe(
        'Existence operator.\n\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
    ),
    value: zod.unknown().optional().describe('Optional value. Runtime behavior determines whether this is ignored.'),
})

export type FeatureFlagFilterPropertyExistsSchemaApi = zod.input<typeof FeatureFlagFilterPropertyExistsSchemaApi>
export type FeatureFlagFilterPropertyExistsSchemaApiOutput = zod.output<typeof FeatureFlagFilterPropertyExistsSchemaApi>

export const DateOperatorEnumApi = zod
    .enum(['is_date_exact', 'is_date_before', 'is_date_after'])
    .describe(
        '\* `is_date_exact` - is_date_exact\n\* `is_date_before` - is_date_before\n\* `is_date_after` - is_date_after'
    )

export type DateOperatorEnumApi = zod.input<typeof DateOperatorEnumApi>
export type DateOperatorEnumApiOutput = zod.output<typeof DateOperatorEnumApi>

export const FeatureFlagFilterPropertyDateSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: DateOperatorEnumApi.describe(
        'Date comparison operator.\n\n\* `is_date_exact` - is_date_exact\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before'
    ),
    value: zod.string().describe('Date value in ISO format or relative date expression.'),
})

export type FeatureFlagFilterPropertyDateSchemaApi = zod.input<typeof FeatureFlagFilterPropertyDateSchemaApi>
export type FeatureFlagFilterPropertyDateSchemaApiOutput = zod.output<typeof FeatureFlagFilterPropertyDateSchemaApi>

export const FeatureFlagFilterPropertySemverSchemaOperatorEnumApi = zod
    .enum([
        'semver_gt',
        'semver_gte',
        'semver_lt',
        'semver_lte',
        'semver_eq',
        'semver_neq',
        'semver_tilde',
        'semver_caret',
        'semver_wildcard',
    ])
    .describe(
        '\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_eq` - semver_eq\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_caret` - semver_caret\n\* `semver_wildcard` - semver_wildcard'
    )

export type FeatureFlagFilterPropertySemverSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertySemverSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertySemverSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertySemverSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertySemverSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: FeatureFlagFilterPropertySemverSchemaOperatorEnumApi.describe(
        'Semantic version comparison operator.\n\n\* `semver_gt` - semver_gt\n\* `semver_gte` - semver_gte\n\* `semver_lt` - semver_lt\n\* `semver_lte` - semver_lte\n\* `semver_eq` - semver_eq\n\* `semver_neq` - semver_neq\n\* `semver_tilde` - semver_tilde\n\* `semver_caret` - semver_caret\n\* `semver_wildcard` - semver_wildcard'
    ),
    value: zod.string().describe('Semantic version string.'),
})

export type FeatureFlagFilterPropertySemverSchemaApi = zod.input<typeof FeatureFlagFilterPropertySemverSchemaApi>
export type FeatureFlagFilterPropertySemverSchemaApiOutput = zod.output<typeof FeatureFlagFilterPropertySemverSchemaApi>

export const FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi = zod
    .enum(['icontains_multi', 'not_icontains_multi'])
    .describe('\* `icontains_multi` - icontains_multi\n\* `not_icontains_multi` - not_icontains_multi')

export type FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertyMultiContainsSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: PropertyGroupTypeEnumApi.optional().describe(
        "Property filter type. Common values are 'person' and 'cohort'.\n\n\* `cohort` - cohort\n\* `person` - person\n\* `group` - group"
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi.describe(
        'Multi-contains operator.\n\n\* `icontains_multi` - icontains_multi\n\* `not_icontains_multi` - not_icontains_multi'
    ),
    value: zod.array(zod.string()).describe('List of strings to evaluate against.'),
})

export type FeatureFlagFilterPropertyMultiContainsSchemaApi = zod.input<
    typeof FeatureFlagFilterPropertyMultiContainsSchemaApi
>
export type FeatureFlagFilterPropertyMultiContainsSchemaApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyMultiContainsSchemaApi
>

export const FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi = zod.enum(['cohort']).describe('\* `cohort` - cohort')

export type FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi
>
export type FeatureFlagFilterPropertyCohortInSchemaTypeEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi
>

export const FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi = zod
    .enum(['in', 'not_in'])
    .describe('\* `in` - in\n\* `not_in` - not_in')

export type FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertyCohortInSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi.describe(
        'Cohort property type required for in\/not_in operators.\n\n\* `cohort` - cohort'
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi.describe(
        'Membership operator for cohort properties.\n\n\* `in` - in\n\* `not_in` - not_in'
    ),
    value: zod.unknown().describe('Cohort comparison value (single or list, depending on usage).'),
})

export type FeatureFlagFilterPropertyCohortInSchemaApi = zod.input<typeof FeatureFlagFilterPropertyCohortInSchemaApi>
export type FeatureFlagFilterPropertyCohortInSchemaApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyCohortInSchemaApi
>

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi = zod.enum(['flag']).describe('\* `flag` - flag')

export type FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi
>
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi
>

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi = zod
    .enum(['flag_evaluates_to'])
    .describe('\* `flag_evaluates_to` - flag_evaluates_to')

export type FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi = zod.input<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi
>
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi
>

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaApi = zod.object({
    key: zod.string().describe('Property key used in this feature flag condition.'),
    type: FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi.describe(
        'Flag property type required for flag dependency checks.\n\n\* `flag` - flag'
    ),
    cohort_name: zod.string().nullish().describe('Resolved cohort name for cohort-type filters.'),
    group_type_index: zod.number().nullish().describe('Group type index when using group-based filters.'),
    operator: FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi.describe(
        'Operator for feature flag dependency evaluation.\n\n\* `flag_evaluates_to` - flag_evaluates_to'
    ),
    value: zod.unknown().describe('Value to compare flag evaluation against.'),
})

export type FeatureFlagFilterPropertyFlagEvaluatesSchemaApi = zod.input<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaApi
>
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaApiOutput = zod.output<
    typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaApi
>

export const FeatureFlagFilterPropertySchemaApi = zod.union([
    FeatureFlagFilterPropertyGenericSchemaApi,
    FeatureFlagFilterPropertyExistsSchemaApi,
    FeatureFlagFilterPropertyDateSchemaApi,
    FeatureFlagFilterPropertySemverSchemaApi,
    FeatureFlagFilterPropertyMultiContainsSchemaApi,
    FeatureFlagFilterPropertyCohortInSchemaApi,
    FeatureFlagFilterPropertyFlagEvaluatesSchemaApi,
])

export type FeatureFlagFilterPropertySchemaApi = zod.input<typeof FeatureFlagFilterPropertySchemaApi>
export type FeatureFlagFilterPropertySchemaApiOutput = zod.output<typeof FeatureFlagFilterPropertySchemaApi>

export const FeatureFlagConditionGroupSchemaApi = zod.object({
    properties: zod
        .array(FeatureFlagFilterPropertySchemaApi)
        .optional()
        .describe('Property conditions for this release condition group.'),
    rollout_percentage: zod.number().optional().describe('Rollout percentage for this release condition group.'),
    variant: zod.string().nullish().describe('Variant key override for multivariate flags.'),
    aggregation_group_type_index: zod
        .number()
        .nullish()
        .describe('Group type index for this condition set. None means person-level aggregation.'),
})

export type FeatureFlagConditionGroupSchemaApi = zod.input<typeof FeatureFlagConditionGroupSchemaApi>
export type FeatureFlagConditionGroupSchemaApiOutput = zod.output<typeof FeatureFlagConditionGroupSchemaApi>

export const FeatureFlagMultivariateVariantSchemaApi = zod.object({
    key: zod.string().describe('Unique key for this variant.'),
    name: zod.string().optional().describe('Human-readable name for this variant.'),
    rollout_percentage: zod.number().describe('Variant rollout percentage.'),
})

export type FeatureFlagMultivariateVariantSchemaApi = zod.input<typeof FeatureFlagMultivariateVariantSchemaApi>
export type FeatureFlagMultivariateVariantSchemaApiOutput = zod.output<typeof FeatureFlagMultivariateVariantSchemaApi>

export const FeatureFlagMultivariateSchemaApi = zod.object({
    variants: zod
        .array(FeatureFlagMultivariateVariantSchemaApi)
        .describe('Variant definitions for multivariate feature flags.'),
})

export type FeatureFlagMultivariateSchemaApi = zod.input<typeof FeatureFlagMultivariateSchemaApi>
export type FeatureFlagMultivariateSchemaApiOutput = zod.output<typeof FeatureFlagMultivariateSchemaApi>

export const featureFlagFiltersSchemaApiEarlyExitDefault = false

export const FeatureFlagFiltersSchemaApi = zod.object({
    groups: zod
        .array(FeatureFlagConditionGroupSchemaApi)
        .optional()
        .describe('Release condition groups for the feature flag.'),
    multivariate: zod
        .union([FeatureFlagMultivariateSchemaApi, zod.null()])
        .optional()
        .describe('Multivariate configuration for variant-based rollouts.'),
    aggregation_group_type_index: zod.number().nullish().describe('Group type index for group-based feature flags.'),
    payloads: zod
        .record(zod.string(), zod.string())
        .optional()
        .describe('Optional payload values keyed by variant key.'),
    feature_enrollment: zod
        .boolean()
        .nullish()
        .describe(
            'Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment\/{flag_key}.'
        ),
    early_exit: zod
        .boolean()
        .default(featureFlagFiltersSchemaApiEarlyExitDefault)
        .describe(
            'When true, condition evaluation stops at the first matching condition set rather than continuing to evaluate subsequent groups.'
        ),
})

export type FeatureFlagFiltersSchemaApi = zod.input<typeof FeatureFlagFiltersSchemaApi>
export type FeatureFlagFiltersSchemaApiOutput = zod.output<typeof FeatureFlagFiltersSchemaApi>

export const FeatureFlagCreateRequestSchemaApi = zod.object({
    key: zod.string().optional().describe('Feature flag key.'),
    name: zod
        .string()
        .optional()
        .describe('Feature flag description (stored in the `name` field for backwards compatibility).'),
    filters: FeatureFlagFiltersSchemaApi.optional().describe('Feature flag targeting configuration.'),
    active: zod.boolean().optional().describe('Whether the feature flag is active.'),
    archived: zod
        .boolean()
        .optional()
        .describe(
            'Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).'
        ),
    tags: zod.array(zod.string()).optional().describe('Organizational tags for this feature flag.'),
    evaluation_contexts: zod
        .array(zod.string())
        .optional()
        .describe('Evaluation contexts that control where this flag evaluates at runtime.'),
    is_remote_configuration: zod
        .boolean()
        .nullish()
        .describe(
            'Whether this flag is a remote configuration flag that delivers a payload rather than gating a feature.'
        ),
    ensure_experience_continuity: zod
        .boolean()
        .nullish()
        .describe(
            "Whether to persist a user's flag value across the anonymous-to-identified transition (the 'persist across authentication steps' option). Incompatible with device_id bucketing."
        ),
    evaluation_runtime: zod
        .union([EvaluationRuntimeEnumApi, zod.null()])
        .optional()
        .describe(
            "Where this flag is allowed to evaluate: 'server' (server-side SDKs only), 'client' (client-side SDKs only), or 'all' (both). Defaults to 'all'.\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All"
        ),
    bucketing_identifier: zod
        .union([BucketingIdentifierEnumApi, zod.null()])
        .optional()
        .describe(
            "Identifier used to bucket users into rollout percentages and variants: 'distinct_id' (user ID, the default) or 'device_id'. Using 'device_id' is incompatible with ensure_experience_continuity=True.\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID"
        ),
})

export type FeatureFlagCreateRequestSchemaApi = zod.input<typeof FeatureFlagCreateRequestSchemaApi>
export type FeatureFlagCreateRequestSchemaApiOutput = zod.output<typeof FeatureFlagCreateRequestSchemaApi>

export const PatchedFeatureFlagPartialUpdateRequestSchemaApi = zod.object({
    key: zod.string().optional().describe('Feature flag key.'),
    name: zod
        .string()
        .optional()
        .describe('Feature flag description (stored in the `name` field for backwards compatibility).'),
    filters: FeatureFlagFiltersSchemaApi.optional().describe('Feature flag targeting configuration.'),
    active: zod.boolean().optional().describe('Whether the feature flag is active.'),
    archived: zod
        .boolean()
        .optional()
        .describe(
            'Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).'
        ),
    tags: zod.array(zod.string()).optional().describe('Organizational tags for this feature flag.'),
    evaluation_contexts: zod
        .array(zod.string())
        .optional()
        .describe('Evaluation contexts that control where this flag evaluates at runtime.'),
    is_remote_configuration: zod
        .boolean()
        .nullish()
        .describe(
            'Whether this flag is a remote configuration flag that delivers a payload rather than gating a feature.'
        ),
    ensure_experience_continuity: zod
        .boolean()
        .nullish()
        .describe(
            "Whether to persist a user's flag value across the anonymous-to-identified transition (the 'persist across authentication steps' option). Incompatible with device_id bucketing."
        ),
    evaluation_runtime: zod
        .union([EvaluationRuntimeEnumApi, zod.null()])
        .optional()
        .describe(
            "Where this flag is allowed to evaluate: 'server' (server-side SDKs only), 'client' (client-side SDKs only), or 'all' (both). Defaults to 'all'.\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All"
        ),
    bucketing_identifier: zod
        .union([BucketingIdentifierEnumApi, zod.null()])
        .optional()
        .describe(
            "Identifier used to bucket users into rollout percentages and variants: 'distinct_id' (user ID, the default) or 'device_id'. Using 'device_id' is incompatible with ensure_experience_continuity=True.\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID"
        ),
})

export type PatchedFeatureFlagPartialUpdateRequestSchemaApi = zod.input<
    typeof PatchedFeatureFlagPartialUpdateRequestSchemaApi
>
export type PatchedFeatureFlagPartialUpdateRequestSchemaApiOutput = zod.output<
    typeof PatchedFeatureFlagPartialUpdateRequestSchemaApi
>

export const ChangeApi = zod.object({
    type: zod.string(),
    action: zod.string(),
    field: zod.string(),
    before: zod.unknown(),
    after: zod.unknown(),
})

export type ChangeApi = zod.input<typeof ChangeApi>
export type ChangeApiOutput = zod.output<typeof ChangeApi>

export const MergeApi = zod.object({
    type: zod.string(),
    source: zod.unknown(),
    target: zod.unknown(),
})

export type MergeApi = zod.input<typeof MergeApi>
export type MergeApiOutput = zod.output<typeof MergeApi>

export const TriggerApi = zod.object({
    job_type: zod.string(),
    job_id: zod.string(),
    payload: zod.unknown(),
})

export type TriggerApi = zod.input<typeof TriggerApi>
export type TriggerApiOutput = zod.output<typeof TriggerApi>

export const DetailApi = zod.object({
    id: zod.string(),
    changes: zod.array(ChangeApi).optional(),
    merge: MergeApi.optional(),
    trigger: TriggerApi.optional(),
    name: zod.string(),
    short_id: zod.string(),
    type: zod.string(),
})

export type DetailApi = zod.input<typeof DetailApi>
export type DetailApiOutput = zod.output<typeof DetailApi>

export const ActivityLogEntryApi = zod.object({
    id: zod.uuid(),
    user: zod.looseObject({}).nullable(),
    activity: zod.string(),
    scope: zod.string(),
    item_id: zod.string(),
    detail: DetailApi.optional(),
    created_at: zod.iso.datetime({ offset: true }),
    is_system: zod.boolean().describe('Whether the activity was performed by the system rather than a user.'),
    was_impersonated: zod.boolean().describe('Whether the acting user was being impersonated by PostHog staff.'),
    client: zod
        .string()
        .nullable()
        .describe(
            "API client that triggered the activity, from the x-posthog-client request header (e.g. 'mcp'). Null for requests that did not send the header."
        ),
})

export type ActivityLogEntryApi = zod.input<typeof ActivityLogEntryApi>
export type ActivityLogEntryApiOutput = zod.output<typeof ActivityLogEntryApi>

export const ActivityLogPaginatedResponseApi = zod
    .object({
        results: zod.array(ActivityLogEntryApi),
        next: zod.url().nullable(),
        previous: zod.url().nullable(),
        total_count: zod.number(),
    })
    .describe('Response shape for paginated activity log endpoints.')

export type ActivityLogPaginatedResponseApi = zod.input<typeof ActivityLogPaginatedResponseApi>
export type ActivityLogPaginatedResponseApiOutput = zod.output<typeof ActivityLogPaginatedResponseApi>

export const DependentFlagApi = zod.object({
    id: zod.number().describe('Feature flag ID'),
    key: zod.string().describe('Feature flag key'),
    name: zod.string().describe('Feature flag name'),
})

export type DependentFlagApi = zod.input<typeof DependentFlagApi>
export type DependentFlagApiOutput = zod.output<typeof DependentFlagApi>

export const FeatureFlagRolloutSummaryApi = zod.object({
    effectively_full_rollout: zod
        .boolean()
        .describe(
            "True if the flag is effectively rolled out to everyone, independent of recent evaluation. For boolean flags this means at least one release condition targets 100% with no property filters (or there are no release conditions); for multivariate flags it means a single variant is served to 100% via a fully rolled out release condition. This is the signal for 'fully rolled out' \/ GA — unlike `status`, which only reflects recent evaluation."
        ),
    has_targeting_conditions: zod
        .boolean()
        .describe(
            'True if any release condition has property filters, i.e. the flag is conditionally targeted rather than a blanket rollout. When true, `max_rollout_percentage` is a percentage within the targeted segment, not of the whole user base.'
        ),
    max_rollout_percentage: zod
        .number()
        .nullable()
        .describe(
            "Highest rollout percentage (0-100) across the flag's release conditions, treating a missing percentage as 100. Null when the flag has no release conditions. Interpret together with `has_targeting_conditions`."
        ),
    is_multivariate: zod
        .boolean()
        .describe('True if the flag serves multiple variants (has a multivariate variant set).'),
})

export type FeatureFlagRolloutSummaryApi = zod.input<typeof FeatureFlagRolloutSummaryApi>
export type FeatureFlagRolloutSummaryApiOutput = zod.output<typeof FeatureFlagRolloutSummaryApi>

export const FeatureFlagStatusResponseApi = zod.object({
    status: zod
        .string()
        .describe(
            "Flag staleness\/evaluation status: active, stale, archived, deleted, or unknown. 'active' means the flag was recently evaluated (or has no usage data yet) — it does NOT mean the flag is fully rolled out. Use the `rollout` object to determine rollout completeness."
        ),
    reason: zod.string().describe('Human-readable explanation of the status'),
    rollout: FeatureFlagRolloutSummaryApi.describe(
        "Summary of the flag's rollout configuration, for determining whether it is fully rolled out."
    ),
})

export type FeatureFlagStatusResponseApi = zod.input<typeof FeatureFlagStatusResponseApi>
export type FeatureFlagStatusResponseApiOutput = zod.output<typeof FeatureFlagStatusResponseApi>

export const FeatureFlagTestEvaluationRequestApi = zod.object({
    distinct_id: zod
        .string()
        .optional()
        .describe('User distinct ID to test against (mutually exclusive with person_id)'),
    person_id: zod.string().optional().describe('Person ID to test against (mutually exclusive with distinct_id)'),
    timestamp: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            'Optional point-in-time to evaluate the flag against — both flag conditions and person properties are reconstructed as they existed at that timestamp. ISO 8601 with timezone, e.g. ``2026-04-29T15:30:00Z`` or ``2026-04-29T15:30:00+00:00``. Naive timestamps (no timezone) are interpreted as UTC.'
        ),
    groups: zod
        .unknown()
        .optional()
        .describe('Groups for feature flag evaluation (JSON object, defaults to empty dict)'),
})

export type FeatureFlagTestEvaluationRequestApi = zod.input<typeof FeatureFlagTestEvaluationRequestApi>
export type FeatureFlagTestEvaluationRequestApiOutput = zod.output<typeof FeatureFlagTestEvaluationRequestApi>

export const FeatureFlagConditionPropertyAnalysisApi = zod.object({
    key: zod.string().describe('Property key'),
    operator: zod.string().describe('Comparison operator'),
    value: zod.unknown().describe('Expected property value'),
    type: zod.string().describe('Property type (person, group, etc.)'),
    actual_value: zod.unknown().describe('Actual property value from user'),
    matched: zod.boolean().describe('Whether this property condition matched'),
    explanation: zod.string().describe('Human-readable explanation of the match result'),
})

export type FeatureFlagConditionPropertyAnalysisApi = zod.input<typeof FeatureFlagConditionPropertyAnalysisApi>
export type FeatureFlagConditionPropertyAnalysisApiOutput = zod.output<typeof FeatureFlagConditionPropertyAnalysisApi>

export const FeatureFlagConditionAnalysisApi = zod.object({
    index: zod.number().describe('Index of this condition in the feature flag'),
    matched: zod
        .boolean()
        .describe(
            "True when this condition was the one that determined the flag's outcome. Use this to find the winning condition — at most one condition per flag is True."
        ),
    properties_matched: zod
        .boolean()
        .optional()
        .describe(
            'True when every property in this condition evaluated to true, regardless of whether this condition was the eventual winner.'
        ),
    explanation: zod.string().describe("Human-readable explanation of why this condition matched\/didn't match"),
    rollout_percentage: zod.number().describe('Rollout percentage for this condition (0.0-100.0)'),
    rollout_excluded: zod
        .boolean()
        .describe('Whether this condition matched properties but was excluded due to rollout'),
    variant: zod.string().nullable().describe('Variant associated with this condition'),
    properties: zod
        .array(FeatureFlagConditionPropertyAnalysisApi)
        .describe('Analysis of each property in this condition'),
})

export type FeatureFlagConditionAnalysisApi = zod.input<typeof FeatureFlagConditionAnalysisApi>
export type FeatureFlagConditionAnalysisApiOutput = zod.output<typeof FeatureFlagConditionAnalysisApi>

export const FeatureFlagTestEvaluationResponseApi = zod.object({
    flag_key: zod.string().describe('Feature flag key'),
    result: zod.unknown().describe('The evaluated value of the feature flag (boolean or variant key string)'),
    reason: zod.string().describe('The reason for the evaluation result'),
    condition_index: zod.number().nullable().describe('The index of the condition that matched, if applicable'),
    payload: zod.unknown().describe('Payload associated with the flag result, if any'),
    person_properties: zod
        .record(zod.string(), zod.unknown())
        .describe('Person properties at the time of evaluation (for historical evaluations)'),
    evaluation_distinct_id: zod
        .string()
        .nullable()
        .describe(
            "The distinct_id used for rollout\/variant bucketing. Echoes the caller-provided distinct_id when one was sent; null on the person_id path so the endpoint doesn't leak the person's other distinct_ids to a feature_flag:read-only token."
        ),
    conditions: zod
        .array(FeatureFlagConditionAnalysisApi)
        .describe('Detailed analysis of each condition in the feature flag'),
})

export type FeatureFlagTestEvaluationResponseApi = zod.input<typeof FeatureFlagTestEvaluationResponseApi>
export type FeatureFlagTestEvaluationResponseApiOutput = zod.output<typeof FeatureFlagTestEvaluationResponseApi>

export const featureFlagVersionResponseApiKeyMax = 400

export const featureFlagVersionResponseApiVersionMin = -2147483648
export const featureFlagVersionResponseApiVersionMax = 2147483647

export const FeatureFlagVersionResponseApi = zod
    .object({
        id: zod.number(),
        key: zod.string().max(featureFlagVersionResponseApiKeyMax),
        name: zod.string().optional(),
        filters: zod.record(zod.string(), zod.unknown()),
        active: zod.boolean().optional(),
        deleted: zod.boolean().optional(),
        version: zod
            .number()
            .min(featureFlagVersionResponseApiVersionMin)
            .max(featureFlagVersionResponseApiVersionMax)
            .nullish(),
        ensure_experience_continuity: zod.boolean().nullish(),
        has_enriched_analytics: zod.boolean().nullish(),
        is_remote_configuration: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        evaluation_runtime: zod
            .union([EvaluationRuntimeEnumApi, BlankEnumApi, zod.null()])
            .optional()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
            ),
        bucketing_identifier: zod
            .union([BucketingIdentifierEnumApi, BlankEnumApi, zod.null()])
            .optional()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'
            ),
        last_called_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('Last time this feature flag was called (from $feature_flag_called events)'),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: zod.number().nullable(),
        is_historical: zod
            .boolean()
            .describe('False for the current version; true for reconstructed historical versions.'),
        version_timestamp: zod.iso.datetime({ offset: true }).nullable(),
        modified_by: zod.number().nullable().describe('User from the activity log entry that produced this version.'),
    })
    .describe('Feature flag state at a given version plus reconstruction metadata.')

export type FeatureFlagVersionResponseApi = zod.input<typeof FeatureFlagVersionResponseApi>
export type FeatureFlagVersionResponseApiOutput = zod.output<typeof FeatureFlagVersionResponseApi>

export const ActiveEnumApi = zod
    .enum(['true', 'false', 'STALE'])
    .describe('\* `true` - true\n\* `false` - false\n\* `STALE` - STALE')

export type ActiveEnumApi = zod.input<typeof ActiveEnumApi>
export type ActiveEnumApiOutput = zod.output<typeof ActiveEnumApi>

export const BulkDeleteFiltersTypeEnumApi = zod
    .enum(['boolean', 'multivariant', 'experiment', 'remote_config'])
    .describe(
        '\* `boolean` - boolean\n\* `multivariant` - multivariant\n\* `experiment` - experiment\n\* `remote_config` - remote_config'
    )

export type BulkDeleteFiltersTypeEnumApi = zod.input<typeof BulkDeleteFiltersTypeEnumApi>
export type BulkDeleteFiltersTypeEnumApiOutput = zod.output<typeof BulkDeleteFiltersTypeEnumApi>

export const BulkDeleteFiltersApi = zod
    .object({
        active: ActiveEnumApi.optional().describe(
            'Filter by active state.\n\n\* `true` - true\n\* `false` - false\n\* `STALE` - STALE'
        ),
        created_by_id: zod.number().optional().describe('Filter to flags created by a specific user ID.'),
        search: zod.string().optional().describe('Search by feature flag key or name (case-insensitive).'),
        type: BulkDeleteFiltersTypeEnumApi.optional().describe(
            'Filter by flag type.\n\n\* `boolean` - boolean\n\* `multivariant` - multivariant\n\* `experiment` - experiment\n\* `remote_config` - remote_config'
        ),
        evaluation_runtime: EvaluationRuntimeEnumApi.optional().describe(
            'Filter by evaluation runtime.\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
        ),
        excluded_properties: zod
            .string()
            .optional()
            .describe('JSON-encoded property filter to exclude. Same shape as the list endpoint.'),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names to filter by. Flags carrying at least one of these tags match.'),
        excluded_tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names to exclude. Flags carrying any of these tags are filtered out.'),
        has_evaluation_contexts: zod
            .boolean()
            .optional()
            .describe('When true, only matches flags with at least one evaluation context.'),
        archived: zod
            .boolean()
            .optional()
            .describe('Filter by archived state. When omitted, archived flags are excluded.'),
    })
    .describe("Allowed filter keys for bulk_delete — same shape as the list endpoint's query params.")

export type BulkDeleteFiltersApi = zod.input<typeof BulkDeleteFiltersApi>
export type BulkDeleteFiltersApiOutput = zod.output<typeof BulkDeleteFiltersApi>

export const BulkDeleteRequestApi = zod.object({
    filters: BulkDeleteFiltersApi.optional().describe(
        "Filter criteria — same shape as the list endpoint's query params. Mutually exclusive with `ids`. Use this to bulk-delete by search\/active\/tags\/etc. instead of supplying explicit IDs."
    ),
    ids: zod
        .array(zod.number().min(1))
        .optional()
        .describe('Explicit feature flag IDs to soft-delete. Mutually exclusive with `filters`.'),
})

export type BulkDeleteRequestApi = zod.input<typeof BulkDeleteRequestApi>
export type BulkDeleteRequestApiOutput = zod.output<typeof BulkDeleteRequestApi>

export const RolloutStateEnumApi = zod
    .enum(['fully_rolled_out', 'not_rolled_out', 'partial'])
    .describe('\* `fully_rolled_out` - fully_rolled_out\n\* `not_rolled_out` - not_rolled_out\n\* `partial` - partial')

export type RolloutStateEnumApi = zod.input<typeof RolloutStateEnumApi>
export type RolloutStateEnumApiOutput = zod.output<typeof RolloutStateEnumApi>

export const BulkDeleteDeletedItemApi = zod.object({
    id: zod.number().describe('ID of the soft-deleted flag.'),
    key: zod.string().describe('The flag key at the time of deletion.'),
    rollout_state: RolloutStateEnumApi.describe(
        'Rollout state captured before deletion.\n\n\* `fully_rolled_out` - fully_rolled_out\n\* `not_rolled_out` - not_rolled_out\n\* `partial` - partial'
    ),
    active_variant: zod
        .string()
        .nullable()
        .describe('Variant key when a multivariate flag was fully rolled out to a single variant; otherwise null.'),
})

export type BulkDeleteDeletedItemApi = zod.input<typeof BulkDeleteDeletedItemApi>
export type BulkDeleteDeletedItemApiOutput = zod.output<typeof BulkDeleteDeletedItemApi>

export const BulkDeleteErrorItemApi = zod.object({
    id: zod
        .unknown()
        .describe('Feature flag ID — integer for valid inputs; the original raw value for invalid inputs.'),
    key: zod.string().optional().describe('The flag key, when known.'),
    reason: zod.string().describe('Human-readable reason the flag could not be deleted.'),
})

export type BulkDeleteErrorItemApi = zod.input<typeof BulkDeleteErrorItemApi>
export type BulkDeleteErrorItemApiOutput = zod.output<typeof BulkDeleteErrorItemApi>

export const BulkDeleteResponseApi = zod
    .object({
        deleted: zod.array(BulkDeleteDeletedItemApi).describe('Flags successfully soft-deleted.'),
        errors: zod.array(BulkDeleteErrorItemApi).describe('Flags that could not be deleted, with reasons.'),
    })
    .describe(
        "Schema-only — referenced from ``@extend_schema(responses=...)`` to describe the wire format.\nNever instantiate this for validation or call ``.is_valid()`` \/ ``.errors`` on it: the\ndeclared ``errors`` field shadows DRF's inherited ``Serializer.errors`` ReturnDict property,\nso accessing ``serializer.errors`` would return this field descriptor instead of validation\nerrors. The handler builds the response dict directly; this class exists only so drf-spectacular\ncan render the response in the OpenAPI spec and downstream generated clients."
    )

export type BulkDeleteResponseApi = zod.input<typeof BulkDeleteResponseApi>
export type BulkDeleteResponseApiOutput = zod.output<typeof BulkDeleteResponseApi>

export const BulkKeysRequestApi = zod.object({
    ids: zod
        .array(zod.unknown())
        .optional()
        .describe(
            'Feature flag IDs to look up keys for. Strings of digits are also accepted; any other value is reported in the response `warning` field and otherwise ignored.'
        ),
})

export type BulkKeysRequestApi = zod.input<typeof BulkKeysRequestApi>
export type BulkKeysRequestApiOutput = zod.output<typeof BulkKeysRequestApi>

export const BulkKeysResponseApi = zod.object({
    keys: zod
        .record(zod.string(), zod.string())
        .describe('Mapping of feature flag ID (as a string) to flag key, for IDs that exist in this project.'),
    warning: zod.string().optional().describe('Present when some submitted IDs were not numeric and were ignored.'),
})

export type BulkKeysResponseApi = zod.input<typeof BulkKeysResponseApi>
export type BulkKeysResponseApiOutput = zod.output<typeof BulkKeysResponseApi>

export const BulkUpdateTagsActionEnumApi = zod
    .enum(['add', 'remove', 'set'])
    .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')

export type BulkUpdateTagsActionEnumApi = zod.input<typeof BulkUpdateTagsActionEnumApi>
export type BulkUpdateTagsActionEnumApiOutput = zod.output<typeof BulkUpdateTagsActionEnumApi>

export const bulkUpdateTagsRequestApiIdsMax = 500

export const BulkUpdateTagsRequestApi = zod.object({
    ids: zod.array(zod.number()).max(bulkUpdateTagsRequestApiIdsMax).describe('List of object IDs to update tags on.'),
    action: BulkUpdateTagsActionEnumApi.describe(
        "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
    ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

export type BulkUpdateTagsRequestApi = zod.input<typeof BulkUpdateTagsRequestApi>
export type BulkUpdateTagsRequestApiOutput = zod.output<typeof BulkUpdateTagsRequestApi>

export const BulkUpdateTagsItemApi = zod.object({
    id: zod.number(),
    tags: zod.array(zod.string()),
})

export type BulkUpdateTagsItemApi = zod.input<typeof BulkUpdateTagsItemApi>
export type BulkUpdateTagsItemApiOutput = zod.output<typeof BulkUpdateTagsItemApi>

export const BulkUpdateTagsErrorApi = zod.object({
    id: zod.number(),
    reason: zod.string(),
})

export type BulkUpdateTagsErrorApi = zod.input<typeof BulkUpdateTagsErrorApi>
export type BulkUpdateTagsErrorApiOutput = zod.output<typeof BulkUpdateTagsErrorApi>

export const BulkUpdateTagsResponseApi = zod.object({
    updated: zod.array(BulkUpdateTagsItemApi),
    skipped: zod.array(BulkUpdateTagsErrorApi),
})

export type BulkUpdateTagsResponseApi = zod.input<typeof BulkUpdateTagsResponseApi>
export type BulkUpdateTagsResponseApiOutput = zod.output<typeof BulkUpdateTagsResponseApi>

export const minimalFeatureFlagApiKeyMax = 400

export const minimalFeatureFlagApiVersionMin = -2147483648
export const minimalFeatureFlagApiVersionMax = 2147483647

export const MinimalFeatureFlagApi = zod.object({
    id: zod.number(),
    team_id: zod.number(),
    name: zod.string().optional(),
    key: zod.string().max(minimalFeatureFlagApiKeyMax),
    filters: zod.record(zod.string(), zod.unknown()).optional(),
    deleted: zod.boolean().optional(),
    active: zod.boolean().optional(),
    ensure_experience_continuity: zod.boolean().nullish(),
    version: zod.number().min(minimalFeatureFlagApiVersionMin).max(minimalFeatureFlagApiVersionMax).nullish(),
    evaluation_runtime: zod
        .union([EvaluationRuntimeEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Specifies where this feature flag should be evaluated\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
        ),
    bucketing_identifier: zod
        .union([BucketingIdentifierEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Identifier used for bucketing users into rollout and variants\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'
        ),
    evaluation_contexts: zod.array(zod.string()),
})

export type MinimalFeatureFlagApi = zod.input<typeof MinimalFeatureFlagApi>
export type MinimalFeatureFlagApiOutput = zod.output<typeof MinimalFeatureFlagApi>

export const MyFlagsResponseApi = zod.object({
    feature_flag: MinimalFeatureFlagApi,
    value: zod.unknown(),
})

export type MyFlagsResponseApi = zod.input<typeof MyFlagsResponseApi>
export type MyFlagsResponseApiOutput = zod.output<typeof MyFlagsResponseApi>

export const UserBlastRadiusRequestApi = zod.object({
    condition: zod.record(zod.string(), zod.unknown()).describe('The release condition to evaluate'),
    group_type_index: zod
        .number()
        .nullish()
        .describe('Group type index for group-based flags (null for person-based flags)'),
})

export type UserBlastRadiusRequestApi = zod.input<typeof UserBlastRadiusRequestApi>
export type UserBlastRadiusRequestApiOutput = zod.output<typeof UserBlastRadiusRequestApi>

export const UserBlastRadiusResponseApi = zod.object({
    affected: zod
        .number()
        .describe('Number of entities matching the condition (users or groups depending on group_type_index)'),
    total: zod.number().describe('Total number of entities of this type in the project'),
})

export type UserBlastRadiusResponseApi = zod.input<typeof UserBlastRadiusResponseApi>
export type UserBlastRadiusResponseApiOutput = zod.output<typeof UserBlastRadiusResponseApi>

export const FlagValueItemApi = zod.object({
    name: zod.unknown(),
})

export type FlagValueItemApi = zod.input<typeof FlagValueItemApi>
export type FlagValueItemApiOutput = zod.output<typeof FlagValueItemApi>

export const FlagValueResponseApi = zod.object({
    results: zod.array(FlagValueItemApi),
    refreshing: zod.boolean(),
})

export type FlagValueResponseApi = zod.input<typeof FlagValueResponseApi>
export type FlagValueResponseApiOutput = zod.output<typeof FlagValueResponseApi>

export const ModelNameEnumApi = zod.enum(['FeatureFlag']).describe('\* `FeatureFlag` - feature flag')

export type ModelNameEnumApi = zod.input<typeof ModelNameEnumApi>
export type ModelNameEnumApiOutput = zod.output<typeof ModelNameEnumApi>

export const ScheduledChangeRecurrenceIntervalEnumApi = zod
    .enum(['daily', 'weekly', 'monthly', 'yearly'])
    .describe('\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly\n\* `yearly` - yearly')

export type ScheduledChangeRecurrenceIntervalEnumApi = zod.input<typeof ScheduledChangeRecurrenceIntervalEnumApi>
export type ScheduledChangeRecurrenceIntervalEnumApiOutput = zod.output<typeof ScheduledChangeRecurrenceIntervalEnumApi>

export const scheduledChangeApiRecordIdMax = 200

export const scheduledChangeApiIsRecurringDefault = false
export const scheduledChangeApiCronExpressionMax = 100

export const ScheduledChangeApi = zod.object({
    id: zod.number(),
    team_id: zod.number(),
    record_id: zod
        .string()
        .max(scheduledChangeApiRecordIdMax)
        .describe('The ID of the record to modify (e.g. the feature flag ID).'),
    model_name: ModelNameEnumApi.describe(
        'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n\* `FeatureFlag` - feature flag'
    ),
    payload: zod
        .unknown()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true\/false to enable\/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    executed_at: zod.iso.datetime({ offset: true }).nullable(),
    failure_reason: zod.string().nullable().describe('Return the safely formatted failure reason instead of raw data.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    updated_at: zod.iso.datetime({ offset: true }),
    is_recurring: zod
        .boolean()
        .default(scheduledChangeApiIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([ScheduledChangeRecurrenceIntervalEnumApi, zod.null()])
        .optional()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly\n\* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(scheduledChangeApiCronExpressionMax).nullish(),
    last_executed_at: zod.iso.datetime({ offset: true }).nullable(),
    end_date: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
    timezone: zod.string().nullable(),
})

export type ScheduledChangeApi = zod.input<typeof ScheduledChangeApi>
export type ScheduledChangeApiOutput = zod.output<typeof ScheduledChangeApi>

export const PaginatedScheduledChangeListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ScheduledChangeApi),
})

export type PaginatedScheduledChangeListApi = zod.input<typeof PaginatedScheduledChangeListApi>
export type PaginatedScheduledChangeListApiOutput = zod.output<typeof PaginatedScheduledChangeListApi>

export const patchedScheduledChangeApiRecordIdMax = 200

export const patchedScheduledChangeApiIsRecurringDefault = false
export const patchedScheduledChangeApiCronExpressionMax = 100

export const PatchedScheduledChangeApi = zod.object({
    id: zod.number().optional(),
    team_id: zod.number().optional(),
    record_id: zod
        .string()
        .max(patchedScheduledChangeApiRecordIdMax)
        .optional()
        .describe('The ID of the record to modify (e.g. the feature flag ID).'),
    model_name: ModelNameEnumApi.optional().describe(
        'The type of record to modify. Currently only \"FeatureFlag\" is supported.\n\n\* `FeatureFlag` - feature flag'
    ),
    payload: zod
        .unknown()
        .optional()
        .describe(
            "The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true\/false to enable\/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe("ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z')."),
    executed_at: zod.iso.datetime({ offset: true }).nullish(),
    failure_reason: zod.string().nullish().describe('Return the safely formatted failure reason instead of raw data.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    is_recurring: zod
        .boolean()
        .default(patchedScheduledChangeApiIsRecurringDefault)
        .describe("Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules."),
    recurrence_interval: zod
        .union([ScheduledChangeRecurrenceIntervalEnumApi, zod.null()])
        .optional()
        .describe(
            'How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly\n\* `yearly` - yearly'
        ),
    cron_expression: zod.string().max(patchedScheduledChangeApiCronExpressionMax).nullish(),
    last_executed_at: zod.iso.datetime({ offset: true }).nullish(),
    end_date: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Optional ISO 8601 datetime after which a recurring schedule stops executing.'),
    timezone: zod.string().nullish(),
})

export type PatchedScheduledChangeApi = zod.input<typeof PatchedScheduledChangeApi>
export type PatchedScheduledChangeApiOutput = zod.output<typeof PatchedScheduledChangeApi>
