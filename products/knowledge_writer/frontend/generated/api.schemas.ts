/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface MergePushApi {
    /**
     * The 40-character SHA of the master merge commit.
     * @pattern ^[0-9a-f]{40}$
     */
    commit_sha: string
}

export interface MergePushResponseApi {
    /** Always accepted; the merge check runs in the background. */
    status: string
}
