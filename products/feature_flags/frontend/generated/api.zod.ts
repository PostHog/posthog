/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    BulkDeleteRequestApi,
    BulkKeysRequestApi,
    BulkUpdateTagsRequestApi,
    CopyFlagsDependencyRequirementsRequestApi,
    CopyFlagsRequestApi,
    EvaluationContextSuggestionRequestApi,
    FeatureFlagApi,
    FeatureFlagCreateRequestSchemaApi,
    FeatureFlagTestEvaluationRequestApi,
    PatchedFeatureFlagPartialUpdateRequestSchemaApi,
    PatchedScheduledChangeApi,
    ScheduledChangeApi,
    StaffCacheMutationApi,
    StaffTeamConfigMutationApi,
    UserBlastRadiusRequestApi,
} from './api.zod.schemas'

/**
 * Staff-only, unscoped status/entry/rebuild/clear for the HyperCache-backed flag caches.
 *
 * Rebuild/clear act on two logical targets: 'evaluation' (the /flags cache) and 'definitions'
 * (the /flags/definitions local-eval cache), independently readable and mutable.
 *
 * Reuses the existing cache functions and Celery tasks (the same mechanism signal handlers use
 * when a flag changes) rather than re-implementing cache-write logic. Registered on the root
 * router so it is not team-nested; staff act on teams they do not belong to.
 */
export const FeatureFlagsStaffCacheClearCreateBody = StaffCacheMutationApi

/**
 * Staff-only, unscoped status/entry/rebuild/clear for the HyperCache-backed flag caches.
 *
 * Rebuild/clear act on two logical targets: 'evaluation' (the /flags cache) and 'definitions'
 * (the /flags/definitions local-eval cache), independently readable and mutable.
 *
 * Reuses the existing cache functions and Celery tasks (the same mechanism signal handlers use
 * when a flag changes) rather than re-implementing cache-write logic. Registered on the root
 * router so it is not team-nested; staff act on teams they do not belong to.
 */
export const FeatureFlagsStaffCacheRebuildCreateBody = StaffCacheMutationApi

/**
 * Staff-only, unscoped read/write for TeamFeatureFlagsConfig (currently just
 * minimal_flag_called_events).
 *
 * Single-team writes only, by design: this setting is meant to be flipped one team at a time
 * after staff manually verify that team's SDK versions support the slim $feature_flag_called
 * event shape, unlike the cache tools' bulk rebuild/clear.
 *
 * Registered on the root router so it is not team-nested; staff act on teams they do not
 * belong to, same as staff_cache.py / staff_teams.py.
 */
export const FeatureFlagsStaffTeamConfigSetCreateBody = StaffTeamConfigMutationApi

export const FeatureFlagsCopyFlagsCreateBody = CopyFlagsRequestApi

export const FeatureFlagsCopyFlagsDependencyRequirementsCreateBody = CopyFlagsDependencyRequirementsRequestApi

/**
 * Hide an evaluation context name from the flag editor's suggestion list, or restore it.
 *
 * POST hides the name; DELETE restores it. The underlying context row and any flags already
 * using it are never modified — this only controls what gets suggested.
 */
export const OrganizationsProjectsEvaluationContextSuggestionsCreateBody = EvaluationContextSuggestionRequestApi

/**
 * Hide an evaluation context name from the flag editor's suggestion list, or restore it.
 *
 * POST hides the name; DELETE restores it. The underlying context row and any flags already
 * using it are never modified — this only controls what gets suggested.
 */
export const EnvironmentsEvaluationContextSuggestionsCreateBody = EvaluationContextSuggestionRequestApi

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsCreateBody = FeatureFlagCreateRequestSchemaApi

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsUpdateBody = FeatureFlagApi

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsPartialUpdateBody = PatchedFeatureFlagPartialUpdateRequestSchemaApi

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsCreateStaticCohortForFlagCreateBody = FeatureFlagApi

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsDashboardCreateBody = FeatureFlagApi

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsEnrichUsageDashboardCreateBody = FeatureFlagApi

/**
 * Test feature flag evaluation against a specific user at an optional point in time.
 *
 * This endpoint allows testing how a feature flag would evaluate for a specific user,
 * optionally at a historical timestamp. When a timestamp is provided, both the flag
 * conditions and person properties are evaluated as they existed at that time.
 */
export const FeatureFlagsTestEvaluationCreateBody = FeatureFlagTestEvaluationRequestApi

/**
 * Bulk delete feature flags by filter criteria or explicit IDs.
 *
 * Accepts either:
 * - {"filters": {...}} - Same filter params as list endpoint (search, active, type, etc.)
 * - {"ids": [...]} - Explicit list of flag IDs (no limit)
 *
 * Returns same format as bulk_delete for UI compatibility.
 *
 * Uses bulk operations for efficiency: database updates are batched and cache
 * invalidation happens once at the end rather than per-flag.
 */
export const FeatureFlagsBulkDeleteCreateBody = BulkDeleteRequestApi

/**
 * Get feature flag keys by IDs.
 * Accepts a list of feature flag IDs and returns a mapping of ID to key.
 */
export const FeatureFlagsBulkKeysRetrieveBody = BulkKeysRequestApi

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const FeatureFlagsBulkUpdateTagsCreateBody = BulkUpdateTagsRequestApi

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
 *
 * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export const FeatureFlagsUserBlastRadiusCreateBody = UserBlastRadiusRequestApi

/**
 * Create, read, update and delete scheduled changes.
 */
export const ScheduledChangesCreateBody = ScheduledChangeApi

/**
 * Create, read, update and delete scheduled changes.
 */
export const ScheduledChangesUpdateBody = ScheduledChangeApi

/**
 * Create, read, update and delete scheduled changes.
 */
export const ScheduledChangesPartialUpdateBody = PatchedScheduledChangeApi
