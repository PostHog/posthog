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

export const releasesCreateBodyNameMax = 255

export const ReleasesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(releasesCreateBodyNameMax).describe('Name of the feature.'),
    description: zod.string().optional().describe('What the feature does for the people who get it.'),
    owner_id: zod.number().nullish().describe('ID of the user who owns the release of this feature.'),
    feature_flag_ids: zod.array(zod.number()).optional().describe('IDs of the feature flags that gate this feature.'),
})

export const releasesPartialUpdateBodyNameMax = 255

export const ReleasesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(releasesPartialUpdateBodyNameMax).optional().describe('Name of the feature.'),
    description: zod.string().optional().describe('What the feature does for the people who get it.'),
    owner_id: zod.number().nullish().describe('ID of the user who owns the release of this feature.'),
    feature_flag_ids: zod.array(zod.number()).optional().describe('IDs of the feature flags that gate this feature.'),
})
