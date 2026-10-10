import type { ResponseMeta } from '../client'

/** Input to feature-flag-archive, backed by feature_flags_archive_create. */
export interface FeatureFlagsArchiveInput {
    /** A unique integer value identifying this feature flag. */
    id: number
}

export interface FeatureFlagsArchiveOutput {
    data: FeatureFlagsArchiveData
    meta: ResponseMeta
}

/**
 * The YAML's response.include projection, followed by enrich_url.
 * @sourceDescription Serializer mixin that handles tags for objects.
 */
export interface FeatureFlagsArchiveData {
    readonly id: number
    /** @maxLength 400 */
    key: string
    active?: boolean
    /** Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`). */
    archived?: boolean
    /** Staleness classification: ACTIVE, STALE, ARCHIVED, DELETED or UNKNOWN. This is not the serving state. Read the `active` field for that. A disabled flag that is not archived or deleted reports ACTIVE, because disabled flags are not evaluated for staleness. */
    readonly status: string
    version?: number
    /** URL of this feature flag in the public PostHog UI. */
    _posthogUrl: string
}
