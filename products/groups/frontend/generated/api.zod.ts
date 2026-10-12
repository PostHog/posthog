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

export const groupsTypesCreateDetailDashboardUpdateBodyNameSingularMax = 400

export const groupsTypesCreateDetailDashboardUpdateBodyNamePluralMax = 400

export const GroupsTypesCreateDetailDashboardUpdateBody = /* @__PURE__ */ zod.object({
    name_singular: zod.string().max(groupsTypesCreateDetailDashboardUpdateBodyNameSingularMax).nullish(),
    name_plural: zod.string().max(groupsTypesCreateDetailDashboardUpdateBodyNamePluralMax).nullish(),
    detail_dashboard: zod.number().nullish(),
    default_columns: zod.array(zod.string()).nullish(),
    created_at: zod.iso.datetime({ offset: true }).nullish(),
})

export const groupsTypesSetDefaultColumnsUpdateBodyNameSingularMax = 400

export const groupsTypesSetDefaultColumnsUpdateBodyNamePluralMax = 400

export const GroupsTypesSetDefaultColumnsUpdateBody = /* @__PURE__ */ zod.object({
    name_singular: zod.string().max(groupsTypesSetDefaultColumnsUpdateBodyNameSingularMax).nullish(),
    name_plural: zod.string().max(groupsTypesSetDefaultColumnsUpdateBodyNamePluralMax).nullish(),
    detail_dashboard: zod.number().nullish(),
    default_columns: zod.array(zod.string()).nullish(),
    created_at: zod.iso.datetime({ offset: true }).nullish(),
})

export const groupsTypesUpdateMetadataPartialUpdateBodyNameSingularMax = 400

export const groupsTypesUpdateMetadataPartialUpdateBodyNamePluralMax = 400

export const GroupsTypesUpdateMetadataPartialUpdateBody = /* @__PURE__ */ zod.object({
    name_singular: zod.string().max(groupsTypesUpdateMetadataPartialUpdateBodyNameSingularMax).nullish(),
    name_plural: zod.string().max(groupsTypesUpdateMetadataPartialUpdateBodyNamePluralMax).nullish(),
    detail_dashboard: zod.number().nullish(),
    default_columns: zod.array(zod.string()).nullish(),
    created_at: zod.iso.datetime({ offset: true }).nullish(),
})
