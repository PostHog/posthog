import type { JsonValue, ResponseMeta } from '../client'

/** Input to feature-flag-get-all, backed by feature_flags_list. */
export interface FeatureFlagsListInput {
    /**
     * Filter by flag state. `"true"` returns enabled flags, `"false"` returns disabled flags, and `"STALE"`
     * returns enabled flags that PostHog classifies as stale.
     *
     * @sourceDescription 'true' and 'false' filter on serving state, the flag's `active` column. 'STALE' returns enabled flags only, so a disabled flag is never STALE. An enabled flag matches when its last recorded `$feature_flag_called` event is more than 30 days old. With no recorded event, it matches when it is at least 30 days old and either stores `filters` as `{}` or serves one result to everyone through a release condition at 100% with no property filters. A flag with no recorded event and an empty `groups` list does not match, even when its `status` reads STALE. The reverse also happens: a multivariate flag matches when a variant is at 100% under a release condition at 100% with no property filters, or when that condition names a variant. Its `status` can still read ACTIVE, because an earlier variant in the list or an earlier targeted condition can serve a different result. In a flag of either type that mixes person and group aggregation, the filter also counts a group-aggregated condition at 100% with no property filters, which `status` does not. An SDK that sends no `$feature_flag_called` event leaves no record, so a STALE flag can still be in use.
     * @see products/feature_flags/mcp/tools.yaml#/tools/feature-flag-get-all/param_overrides/active/description
     */
    active?: 'true' | 'false' | 'STALE'
    /** Filter by archived state. When omitted, archived flags are excluded. */
    archived?: 'true' | 'false'
    /** Filter by the user(s) who created the feature flag. Accepts a single user ID, or a JSON-encoded / comma-separated list of user IDs to match any of them. */
    created_by_id?: string
    /** When 'true', only return flags that can back an experiment: multivariate with 2-20 variants. Any other value is ignored. */
    eligible_for_experiment?: 'true'
    /** Filter feature flags by their evaluation runtime. */
    evaluation_runtime?: 'all' | 'client' | 'server'
    /** JSON-encoded list of feature flag keys to exclude from the results. */
    excluded_properties?: string
    /** JSON-encoded list of tag names to exclude. Flags carrying any of these tags are filtered out. */
    excluded_tags?: string
    /** Filter feature flags by presence of evaluation contexts. 'true' returns only flags with at least one evaluation context, 'false' returns only flags without. */
    has_evaluation_contexts?: 'true' | 'false'
    /** Filter by exact feature flag key match. Case insensitive. */
    key?: string
    /** Number of results to return per page. */
    limit?: number
    /** The initial index from which to return the results. */
    offset?: number
    /**
     * Search by feature flag key or name (case-insensitive). Use this to find the flag ID for get/update/delete
     * tools.
     *
     * @sourceDescription Search by feature flag key or name. Case insensitive. Spaces, underscores, and hyphens count as the same separator.
     * @see products/feature_flags/mcp/tools.yaml#/tools/feature-flag-get-all/param_overrides/search/description
     */
    search?: string
    /** JSON-encoded list of tag names to filter feature flags by. */
    tags?: string
    type?: 'boolean' | 'experiment' | 'multivariant' | 'remote_config'
}

export interface FeatureFlagsListOutput {
    data: FeatureFlagsListData
    meta: ResponseMeta
}

export interface FeatureFlagsListData {
    count: number
    next?: string | null
    previous?: string | null
    results: FeatureFlagsListItem[]
    /** URL of the project's feature flag list in the public PostHog UI. */
    _posthogUrl: string
}

/**
 * Each row has the YAML's response.include projection and its own enrich_url.
 * @sourceDescription Serializer mixin that handles tags for objects.
 */
export interface FeatureFlagsListItem {
    readonly id: number
    /** @maxLength 400 */
    key: string
    /** contains the description for the flag (field name `name` is kept for backwards-compatibility) */
    name?: string
    /** @nullable */
    readonly updated_at: string | null
    /** Staleness classification: ACTIVE, STALE, ARCHIVED, DELETED or UNKNOWN. This is not the serving state. Read the `active` field for that. A disabled flag that is not archived or deleted reports ACTIVE, because disabled flags are not evaluated for staleness. */
    readonly status: string
    /** The upstream schema leaves tag elements untyped; no string-only guarantee is available. */
    tags?: JsonValue[]
    /**
     * Last time this feature flag was called (from $feature_flag_called events)
     * @nullable
     */
    readonly last_called_at: string | null
    active?: boolean
    readonly created_at: string
    /** URL of this feature flag in the public PostHog UI. */
    _posthogUrl: string
}
