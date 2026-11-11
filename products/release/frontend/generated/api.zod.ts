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
 * Create a release.
 */
export const releasesCreateBodyNameMax = 255

export const releasesCreateBodyFeatureFlagIdsItemMax = 2147483647

export const ReleasesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(releasesCreateBodyNameMax).describe('Name of the release.'),
    description: zod.string().optional().describe('What changes for the people who get the release.'),
    owner_id: zod
        .number()
        .nullish()
        .describe("ID of the user who owns the release. Must be a member of the project's organization."),
    feature_flag_ids: zod
        .array(zod.number().min(1).max(releasesCreateBodyFeatureFlagIdsItemMax))
        .optional()
        .describe('IDs of the feature flags that control who gets the release.'),
})

/**
 * Change the name, description, owner or linked flags of a release.
 */
export const releasesPartialUpdateBodyNameMax = 255

export const releasesPartialUpdateBodyFeatureFlagIdsItemMax = 2147483647

export const ReleasesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(releasesPartialUpdateBodyNameMax).optional().describe('Name of the release.'),
    description: zod.string().optional().describe('What changes for the people who get the release.'),
    owner_id: zod
        .number()
        .nullish()
        .describe("ID of the user who owns the release. Must be a member of the project's organization."),
    feature_flag_ids: zod
        .array(zod.number().min(1).max(releasesPartialUpdateBodyFeatureFlagIdsItemMax))
        .optional()
        .describe('IDs of the feature flags that control who gets the release.'),
})
