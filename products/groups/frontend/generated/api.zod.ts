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
    group_properties: zod.unknown().optional(),
})

export const GroupsDeletePropertyCreateBody = /* @__PURE__ */ zod.object({
    $unset: zod.string().describe('Name of the property to delete.'),
})

export const GroupsUpdatePropertyCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().describe('Name of the property to set.'),
    value: zod
        .union([zod.string(), zod.number(), zod.boolean(), zod.looseObject({}), zod.array(zod.unknown())])
        .describe('Value to set. Any JSON value other than null.'),
})

export const GroupsTypesCreateDetailDashboardUpdateBody = /* @__PURE__ */ zod.object({
    group_type_index: zod.number().describe('Index of the group type that gets the detail dashboard.'),
})

export const GroupsTypesSetDefaultColumnsUpdateBody = /* @__PURE__ */ zod.object({
    group_type_index: zod.number().describe('Index of the group type to update.'),
    default_columns: zod
        .array(zod.string())
        .describe('Columns that the groups list of this group type shows by default.'),
})

export const groupsTypesUpdateMetadataPartialUpdateBodyNameSingularMax = 400

export const groupsTypesUpdateMetadataPartialUpdateBodyNamePluralMax = 400

export const GroupsTypesUpdateMetadataPartialUpdateBodyItem = /* @__PURE__ */ zod.object({
    group_type_index: zod.number().describe('Index of the group type to update.'),
    name_singular: zod
        .string()
        .max(groupsTypesUpdateMetadataPartialUpdateBodyNameSingularMax)
        .nullish()
        .describe('Singular display name of the group type.'),
    name_plural: zod
        .string()
        .max(groupsTypesUpdateMetadataPartialUpdateBodyNamePluralMax)
        .nullish()
        .describe('Plural display name of the group type.'),
})
export const GroupsTypesUpdateMetadataPartialUpdateBody = /* @__PURE__ */ zod.array(
    GroupsTypesUpdateMetadataPartialUpdateBodyItem
)
