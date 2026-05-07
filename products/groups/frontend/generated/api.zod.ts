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

export const groupsCreateBodyGroupTypeIndexMin = -2147483648
export const groupsCreateBodyGroupTypeIndexMax = 2147483647

export const groupsCreateBodyGroupKeyMax = 400

export const GroupsCreateBody = /* @__PURE__ */ zod.object({
    group_type_index: zod.number().min(groupsCreateBodyGroupTypeIndexMin).max(groupsCreateBodyGroupTypeIndexMax),
    group_key: zod.string().max(groupsCreateBodyGroupKeyMax),
    group_properties: zod.unknown().nullish(),
})

export const groupsDeletePropertyCreateBodyGroupTypeIndexMin = -2147483648
export const groupsDeletePropertyCreateBodyGroupTypeIndexMax = 2147483647

export const groupsDeletePropertyCreateBodyGroupKeyMax = 400

export const GroupsDeletePropertyCreateBody = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsDeletePropertyCreateBodyGroupTypeIndexMin)
        .max(groupsDeletePropertyCreateBodyGroupTypeIndexMax),
    group_key: zod.string().max(groupsDeletePropertyCreateBodyGroupKeyMax),
    group_properties: zod.unknown().optional(),
})

export const groupsUpdatePropertyCreateBodyGroupTypeIndexMin = -2147483648
export const groupsUpdatePropertyCreateBodyGroupTypeIndexMax = 2147483647

export const groupsUpdatePropertyCreateBodyGroupKeyMax = 400

export const GroupsUpdatePropertyCreateBody = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsUpdatePropertyCreateBodyGroupTypeIndexMin)
        .max(groupsUpdatePropertyCreateBodyGroupTypeIndexMax),
    group_key: zod.string().max(groupsUpdatePropertyCreateBodyGroupKeyMax),
    group_properties: zod.unknown().optional(),
})
